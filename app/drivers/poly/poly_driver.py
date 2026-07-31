# app/drivers/poly/poly_driver.py
"""
Poly (Polycom RealPresence Group Series) API 드라이버 — Telnet 또는 SSH.

Integrator Reference Guide 기준으로 API 명령 자체는 Telnet/SSH/RS-232 접속
방식과 무관하게 동일하다 (poly_commands.py에서 문서 대조로 확정한 명령만 사용).
Telnet은 telnetlib3(비동기 네이티브)를, SSH는 paramiko(동기)를
CiscoDriver와 동일하게 asyncio.to_thread로 감싸 사용한다.
"""
from __future__ import annotations

import asyncio
import logging
import re
import socket
from collections import deque
from datetime import datetime, timezone

import paramiko
import telnetlib3
from cryptography.hazmat.primitives import hashes

logger = logging.getLogger(__name__)

from app.core.driver_base import (
    CalendarEntry,
    DeviceDriver,
    DeviceStatus,
    DriverAuthError,
    DriverCommandError,
    DriverConnectionError,
    DriverError,
    DriverTimeoutError,
)
from . import poly_commands as cmd


def _allow_legacy_ssh_rsa_hostkey() -> None:
    """paramiko 5.x는 SHA-1 기반 구형 호스트키(ssh-rsa)를 기본 협상 목록에서 제외한다
    (paramiko/transport.py Transport._key_info, _preferred_keys — "do not want ssh-rsa"
    주석으로 의도적으로 뺀 것, 소스로 확인함). 그런데 Poly Group Series 실장비(RoomOS가
    아닌 구형 Group Series SSH 스택)는 ssh-rsa만 제공하는 경우가 있어(2026-07-30 VDI
    실장비 검증에서 `Incompatible ssh peer (no acceptable host key)`로 확인) 연결 자체가
    안 된다.

    협상 허용 목록(_key_info/_preferred_keys)만 고치면 안 된다 — RSAKey.HASHES에도
    "ssh-rsa" -> SHA1 매핑이 빠져 있어서(paramiko/rsakey.py, SHA1 서명 생성/검증 로직
    자체를 없앤 것), 협상은 통과해도 실제 호스트키 서명 검증 단계(verify_ssh_sig)에서
    `sig_algorithm not in self.HASHES`로 조용히 실패한다 — 이 부분까지 같이 복구해야
    실제로 연결된다(2026-07-30 자체 재현 테스트로 확인: 협상 목록만 고쳤을 때는
    서명 단계에서 KeyError로 계속 실패함).

    다른 암호/키교환/MAC 알고리즘은 그대로 최신 기본값을 유지한다 — ssh-rsa 호스트키
    검증 경로 하나만 복구한다."""
    if "ssh-rsa" not in paramiko.Transport._key_info:
        paramiko.Transport._key_info["ssh-rsa"] = paramiko.RSAKey
    if "ssh-rsa" not in paramiko.Transport._preferred_keys:
        paramiko.Transport._preferred_keys = paramiko.Transport._preferred_keys + ("ssh-rsa",)
    if "ssh-rsa" not in paramiko.RSAKey.HASHES:
        paramiko.RSAKey.HASHES["ssh-rsa"] = hashes.SHA1


_GREETING_PREFIX = "Hi, my name is"
"""Poly 세션이 열리면 장비가 스스로 보내는 인사말 줄의 접두어(뒤에 장비 이름이 붙음).
2026-07-31 VDI 2차 재테스트에서 실제 문구("Hi, my name is : 판교 6층 영상회의실")로 확인."""

_PROMPT_ECHO_PREFIX = "-> "
"""장비 셸이 명령을 받을 준비가 되면 "-> " 프롬프트를 찍고, 그 뒤에 방금(또는 훨씬 이전에)
받은 명령을 그대로 에코해 돌려보낸다(예: "-> systemsetting get model", "-> calendarmeetings
list "today""). 이 에코가 도착하는 시점이 불규칙해(한두 교환 뒤에 나타날 수 있음) 실제 응답과
구분하기 어렵지만, "-> "로 시작하는 줄은 지금까지 관찰된 모든 경우에 항상 프롬프트+에코였고
실제 데이터 응답이었던 적은 없다(2026-07-31 VDI 2차 재테스트, /logs 원문 트레이스로 확인)."""


class PolyDriver(DeviceDriver):
    def __init__(
        self,
        host: str,
        port: int = 2323,
        timeout: float = 7.0,
        transport: str = "telnet",
        username: str = "",
        password: str = "",
    ) -> None:
        if transport not in ("telnet", "ssh"):
            raise ValueError(f"invalid transport: {transport!r} (expected 'telnet' or 'ssh')")
        self.host = host
        self.port = port
        self.timeout = timeout
        self.transport = transport
        self.username = username
        self.password = password
        self._reader = None
        self._writer = None
        self._ssh_client: paramiko.SSHClient | None = None
        self._ssh_channel = None
        self._ssh_buffer = b""
        self._model: str | None = None
        # 응답 정렬이 깨진 원인을 진단하려면 마지막 한 줄만으로는 부족하다 — 직전 몇 줄의
        # 원문을 남겨서, 다음에 같은 문제가 재발했을 때 카드에 뜬 한 줄짜리 에러 메시지
        # 대신 실제 읽힌 순서를 그대로 /logs(시스템 로그)에서 확인할 수 있게 한다
        # (2026-07-31 VDI 2차 재테스트 — 원인 후보를 화면 캡처로 하나씩 추측하며 확인하던
        # 방식의 한계를 겪은 뒤 추가).
        self._recent_lines: deque[str] = deque(maxlen=8)

    async def connect(self) -> None:
        if self.transport == "ssh":
            await asyncio.to_thread(self._connect_ssh_sync)
            await asyncio.to_thread(self._drain_startup_noise_ssh_sync)
        else:
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    telnetlib3.open_connection(self.host, self.port), timeout=self.timeout
                )
            except asyncio.TimeoutError as exc:
                raise DriverTimeoutError(f"connect timeout: {self.host}:{self.port}") from exc
            except OSError as exc:
                raise DriverConnectionError(str(exc)) from exc
            await self._drain_startup_noise_telnet()
        await self._fetch_model()

    _STARTUP_DRAIN_PER_READ_TIMEOUT = 0.5
    _STARTUP_DRAIN_MAX_LINES = 20

    async def _drain_startup_noise_telnet(self) -> None:
        """세션을 새로 열면 장비가 명령 요청과 무관하게 여러 줄짜리 인사말 블록을
        스스로 먼저 보낸다("Hi, my name is : <이름>" 다음에도 "Here is what I know
        about myself:" 등 몇 줄이 더 이어짐 — 정확히 몇 줄인지 문서에 없어 예측할 수
        없다는 걸 2026-07-31 VDI 재테스트에서 확인). 첫 명령을 보내기 전에 짧은
        타임아웃으로 반복 읽어서, 더 이상 응답이 없을 때까지(=인사말이 다 끝났을 때까지)
        전부 버린다 — 정확한 줄 수를 가정하지 않아 인사말이 몇 줄이든, 아예 없든 안전하다."""
        if self._reader is None:
            return
        for _ in range(self._STARTUP_DRAIN_MAX_LINES):
            try:
                line = await asyncio.wait_for(
                    self._reader.readline(), timeout=self._STARTUP_DRAIN_PER_READ_TIMEOUT
                )
            except asyncio.TimeoutError:
                return
            if not line:
                return
            self._recent_lines.append(f"<(drain) {line.strip()}")

    def _drain_startup_noise_ssh_sync(self) -> None:
        """SSH 버전 — 원리는 _drain_startup_noise_telnet과 동일. paramiko 채널의
        settimeout()을 잠깐 짧게 바꿔서 여러 줄을 빠르게 소진하고 원래 타임아웃으로
        되돌린다(스레드 안에서 동기로 끝까지 처리 — asyncio.wait_for로 취소하면 recv()가
        블로킹된 채로 스레드가 남아 이후 읽기와 self._ssh_buffer를 두고 경합할 수 있다)."""
        if self._ssh_channel is None:
            return
        self._ssh_channel.settimeout(self._STARTUP_DRAIN_PER_READ_TIMEOUT)
        try:
            for _ in range(self._STARTUP_DRAIN_MAX_LINES):
                try:
                    while b"\n" not in self._ssh_buffer:
                        data = self._ssh_channel.recv(4096)
                        if not data:
                            return
                        self._ssh_buffer += data
                except socket.timeout:
                    return
                line, self._ssh_buffer = self._ssh_buffer.split(b"\n", 1)
                self._recent_lines.append(f"<(drain) {line.decode('utf-8', errors='replace').strip()}")
        finally:
            self._ssh_channel.settimeout(self.timeout)

    async def _fetch_model(self) -> None:
        """모델명은 하드웨어가 바뀌지 않는 한 안 변하므로 연결 시 1회만 조회해 캐시한다.
        조회 실패는 connect() 전체를 실패시키지 않는다(있으면 좋은 정보일 뿐).

        실장비에서 모델 정보가 두 가지 형식으로 나오는 걸 확인했다(2026-07-31 VDI 2차
        재테스트): (1) `systemsetting get model` 직접 조회 응답 —
        `systemsetting model "RealPresence Group 700"`, (2) 세션이 스스로 보내는 자기소개
        블록("Here is what I know about myself:" 뒤에 이어지는) 안의 `Model:
        RealPresence Group 700` 줄 — 이 블록이 명령 응답 자리에 끼어드는 경우가 많아,
        굳이 지나쳐 보내지 않고 여기서 바로 모델명으로 인정한다."""
        try:
            resp = await self._call_expecting(
                cmd.SYSTEMSETTING_GET_MODEL,
                lambda line: line.startswith("systemsetting model") or line.startswith("Model:"),
            )
        except DriverError:
            return
        match = re.search(r'"([^"]+)"', resp)
        if match:
            self._model = match.group(1)
            return
        if resp.startswith("Model:"):
            self._model = resp[len("Model:") :].strip()

    def _connect_ssh_sync(self) -> None:
        _allow_legacy_ssh_rsa_hostkey()
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=self.timeout,
                look_for_keys=False,
                allow_agent=False,
            )
        except paramiko.AuthenticationException as exc:
            raise DriverAuthError(str(exc)) from exc
        except (paramiko.SSHException, OSError) as exc:
            raise DriverConnectionError(str(exc)) from exc

        channel = client.invoke_shell()
        channel.settimeout(self.timeout)
        self._ssh_client = client
        self._ssh_channel = channel
        self._ssh_buffer = b""

    async def disconnect(self) -> None:
        if self.transport == "ssh":
            await asyncio.to_thread(self._disconnect_ssh_sync)
            return
        if self._writer is not None:
            self._writer.close()
        self._reader = None
        self._writer = None

    def _disconnect_ssh_sync(self) -> None:
        if self._ssh_channel is not None:
            try:
                self._ssh_channel.close()
            except (paramiko.SSHException, OSError, EOFError):
                pass
        if self._ssh_client is not None:
            try:
                self._ssh_client.close()
            except (paramiko.SSHException, OSError, EOFError):
                pass
        self._ssh_channel = None
        self._ssh_client = None

    # --- 내부 통신 헬퍼 ---

    async def _send(self, command: str) -> None:
        self._recent_lines.append(f"> {command}")
        if self.transport == "ssh":
            await asyncio.to_thread(self._send_ssh_sync, command)
            return
        if self._writer is None:
            raise DriverConnectionError("not connected")
        try:
            self._writer.write(command + "\r\n")
        except OSError as exc:
            raise DriverConnectionError(str(exc)) from exc

    def _send_ssh_sync(self, command: str) -> None:
        if self._ssh_channel is None:
            raise DriverConnectionError("not connected")
        try:
            self._ssh_channel.send(command + "\r\n")
        except OSError as exc:
            raise DriverConnectionError(str(exc)) from exc

    async def _read_line(self) -> str:
        while True:
            line = await self._read_line_once()
            self._recent_lines.append(f"< {line}")
            if not line:
                # 빈 줄은 이 드라이버가 다루는 어떤 명령에도 정상 응답으로 나타난 적이
                # 없다 — 실장비 로그에서 확인된 모든 사례가 잡음이었다(2026-07-31 VDI
                # 2차 재테스트, 여러 회 재현). 버리고 다음 줄을 읽는다.
                continue
            if line.startswith(_GREETING_PREFIX):
                # 세션을 새로 열면 장비가 명령 요청과 무관하게 인사말 한 줄을 스스로
                # 먼저 보낸다(예: "Hi, my name is : 판교 6층 영상회의실"). connect()에서
                # 인사말 블록 전체를 미리 비우려 시도하지만(_drain_startup_noise_*),
                # 타이밍이 늦어 새어나온 줄이 있을 수 있으므로 여기서도 한 번 더
                # 안전망으로 걸러낸다.
                continue
            if line.startswith(_PROMPT_ECHO_PREFIX):
                # "-> " 프롬프트 + 명령 에코. 어느 명령의 응답 자리에 끼어들든(때로는
                # 몇 교환 뒤늦게) 실제 데이터가 아니므로 버리고 다음 줄을 읽는다.
                continue
            return line

    async def _read_line_once(self) -> str:
        if self.transport == "ssh":
            return await asyncio.to_thread(self._read_line_ssh_sync)
        if self._reader is None:
            raise DriverConnectionError("not connected")
        try:
            line = await asyncio.wait_for(self._reader.readline(), timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            raise DriverTimeoutError("timeout waiting for device response") from exc
        if not line:
            raise DriverConnectionError("connection closed by device")
        return line.strip()

    def _read_line_ssh_sync(self) -> str:
        if self._ssh_channel is None:
            raise DriverConnectionError("not connected")
        while b"\n" not in self._ssh_buffer:
            try:
                data = self._ssh_channel.recv(4096)
            except socket.timeout as exc:
                raise DriverTimeoutError("timeout waiting for device response") from exc
            except OSError as exc:
                raise DriverConnectionError(str(exc)) from exc
            if not data:
                raise DriverConnectionError("connection closed by device")
            self._ssh_buffer += data
        line, self._ssh_buffer = self._ssh_buffer.split(b"\n", 1)
        return line.decode("utf-8", errors="replace").strip()

    async def _call(self, command: str) -> str:
        await self._send(command)
        return await self._read_line()

    _MAX_LAG_SKIPS = 25
    """실장비에서 확인된 패턴: 응답이 명령보다 밀려 들어온다(mute의 진짜 응답이 callinfo
    자리에서 나오는 식 — 2026-07-31 VDI 2차 재테스트, 같은 모양의 트레이스가 5회 이상
    반복 확인됨). 처음엔 "Hi, my name is : <이름>" 한두 줄짜리 인사말로만 봤는데, 실제로는
    "Here is what I know about myself:" 뒤에 Model/Software Version/Build
    Information/Contact Number/Total Calls/Total Time In Calls/SNTP Time Service/Local
    Time is/IP Video Number/MP Enabled/H323 Enabled 등 13줄 넘게 이어지는 자기소개
    블록이고, 연결 직후가 아니라 세션 중 아무 때나(다음 명령을 받아야 그제서야 밀린 출력을
    내보내는 것으로 추정) 통째로 끼어들 수 있다는 게 확인됨 — 3줄로는 부족해서 넉넉하게
    늘림. 첫 줄이 기대와 다르다고 곧장 실패로 단정하지 않고, 밀려 들어온 진짜 응답이
    뒤이어 도착할 가능성을 감안해 몇 줄 더 읽어본다."""

    async def _call_expecting(self, command: str, is_valid) -> str:
        """_call()과 달리 응답이 그럴듯한지(is_valid) 확인하고, 아니면 최대
        _MAX_LAG_SKIPS줄까지 더 읽어 진짜 응답을 찾는다. 그래도 못 찾으면 마지막으로
        읽은 줄을 그대로 반환한다(호출부의 기존 불일치 처리 로직에 맡김 — 실패를
        완전히 숨기지 않는다).

        "info: " 프리픽스는 예외다 — 밀려 들어온 잡음이 아니라 장비가 방금 보낸 명령에
        대해 실제로 답하는 안내/거부 메시지로 확인됐다(2026-07-31 VDI 2차 재테스트:
        `dial phone sip "..."`에 "info: AUDIO call not enabled"로 응답 — 재시도로
        건너뛸 잡음이 아니라 장비가 그 명령 자체를 거부한 것이었는데, 계속 건너뛰다가
        결국 응답이 끊겨 "timeout waiting for device response"로만 보였다). is_valid를
        통과 못 해도 이 줄은 곧장 반환해 호출부가 원문 그대로 실패 이유를 보고하게 한다."""
        await self._send(command)
        line = await self._read_line()
        for _ in range(self._MAX_LAG_SKIPS):
            if is_valid(line) or line.startswith("info:"):
                return line
            logger.info(
                "poly %r got implausible line %r, reading one more (possible one-exchange lag)",
                command,
                line,
            )
            line = await self._read_line()
        return line

    async def _call_block(
        self, command: str, begin: str, end: str, *, allow_single_line: str | None = None
    ) -> list[str]:
        """begin/end 마커로 감싸인 다중 라인 응답을 읽는다.

        allow_single_line을 지정하지 않으면 마커 없이 단일 라인만 와도 그대로 담아
        반환한다(기존 동작 — calendarmeetings 등 실패해도 위험이 낮은 조회에 사용).

        allow_single_line을 지정하면 그 값과 정확히 일치하는 단일 라인만 예외적으로
        허용하고, 그 외의 예상 밖 응답은 DriverCommandError로 올린다(단, 곧장 포기하지
        않고 _call_expecting과 같은 이유로 몇 줄 더 시도해본 뒤에만 포기한다). 세션이
        뒤섞이면(예: 장비가 요청 없이 보내는 notify 줄이 응답 사이에 끼어드는 경우) 이
        분기를 타지 않고 조용히 아무 줄이나 "in_call=True"로 잘못 확정해버리는 문제가
        있었다(2026-07-31 VDI 2차 재테스트에서 재현 — 실제로는 통화중이 아닌데 새로고침을
        해도 계속 통화중으로 표시됨, 관련 오류 로그도 전혀 없었음). 여기서 예외로
        올리면 상위에서 오프라인 처리 + 드라이버 재연결로 이어져 스스로 회복된다."""
        if allow_single_line is not None:
            first = await self._call_expecting(
                command, lambda line: line == begin or line == allow_single_line
            )
        else:
            first = await self._call(command)
        if first == begin:
            lines: list[str] = []
            while True:
                line = await self._read_line()
                if line == end:
                    break
                lines.append(line)
            return lines
        if allow_single_line is None or first == allow_single_line:
            return [first]
        logger.warning(
            "poly session desync on %r — unexpected %r, recent send/recv trace: %s",
            command,
            first,
            list(self._recent_lines),
        )
        raise DriverCommandError(f"unexpected response to {command!r}: {first!r}")

    # --- DeviceDriver 구현 ---

    async def get_status(self) -> DeviceStatus:
        now = datetime.now(timezone.utc).isoformat()
        if self._model is None:
            # connect() 시점의 단발성 모델 조회가 실패(타임아웃/일시적 응답 불일치 등)하면
            # 그 이후로는 재연결 전까지 영영 재시도하지 않아 "모델 확인 중..."에 계속
            # 머무르는 문제가 있었다 — 모델을 아직 못 얻었으면 폴링마다 한 번씩 더 시도한다.
            await self._fetch_model()
        try:
            mute_resp = await self._call_expecting(
                cmd.MUTE_NEAR_GET, lambda line: line in ("mute near on", "mute near off")
            )
            muted = mute_resp == "mute near on"

            call_lines = await self._call_block(
                cmd.CALLINFO_ALL,
                "callinfo begin",
                "callinfo end",
                allow_single_line="system is not in a call",
            )
            in_call = call_lines != ["system is not in a call"]
            call_peer = None
            if in_call:
                # 실장비 원문으로 확인된 형식: "callinfo:<id>::<주소>:384:connected:...".
                # call.id 다음 필드(index 2)가 비어 있고 주소는 index 3에 온다(2026-07-31
                # VDI 2차 재테스트) — 시뮬레이터는 이 빈 필드 없이 index 2에 주소를 바로
                # 넣어 구성했었는데, 그게 잘못된 가정이었다. 이 인덱스 착오 때문에 Poly
                # 카드에는 통화 중 회의 제목이 안 뜨고 Cisco만 떴었다(call_peer가 항상
                # ""였고, 프런트엔드가 Teams 목록의 join_uri와 매칭을 못 함).
                parts = call_lines[0].split(":")
                if len(parts) > 3:
                    call_peer = parts[3]

            # 모델명(_fetch_model)과 같은 이유로 개별 보호: uptime 조회 실패가 통화/음소거
            # 등 나머지 상태 조회까지 offline으로 끌어내리지 않게 한다.
            try:
                uptime_resp = await self._call_expecting(
                    cmd.UPTIME_GET, lambda line: _parse_uptime(line) is not None
                )
                uptime_seconds = _parse_uptime(uptime_resp)
            except DriverError:
                uptime_seconds = None

            return DeviceStatus(
                online=True,
                in_call=in_call,
                muted=muted,
                call_peer=call_peer,
                last_polled_at=now,
                model=self._model,
                uptime_seconds=uptime_seconds,
            )
        except DriverError as exc:
            return DeviceStatus(
                online=False,
                in_call=False,
                muted=False,
                call_peer=None,
                last_polled_at=now,
                error=str(exc),
                model=self._model,
            )

    async def mute(self, on: bool) -> bool:
        expected = "mute near on" if on else "mute near off"
        # 예전에는 불일치 시 그냥 False만 반환해 실패 원인이 로그에 전혀 안 남았다
        # (Cisco 쪽 DriverCommandError처럼 원문을 남겨야 다음에 바로 진단 가능하다 —
        # 2026-07-31 VDI 검증에서 Cisco mute 실패는 원문 덕에 바로 원인을 찾았지만
        # Poly는 원문이 없어 원인 불명이었다). _call_expecting을 쓰는 이유는 응답이
        # 명령보다 한 교환 밀려 들어오는 현상이 실제로 확인됐기 때문(2026-07-31 VDI
        # 2차 재테스트) — 첫 줄이 안 맞아도 곧장 실패로 단정하지 않는다.
        resp = await self._call_expecting(cmd.mute_near(on), lambda line: line == expected)
        if resp != expected:
            raise DriverCommandError(f"unexpected response to {cmd.mute_near(on)!r}: {resp!r}")
        return True

    async def dial(self, address: str) -> bool:
        resp = await self._call_expecting(cmd.dial_manual(address), lambda line: line.startswith("dialing"))
        if not resp.startswith("dialing"):
            raise DriverCommandError(f"unexpected response to dial: {resp!r}")
        return True

    async def hangup(self) -> bool:
        resp = await self._call_expecting(cmd.hangup_video(), lambda line: line == "hanging up video")
        if resp != "hanging up video":
            raise DriverCommandError(f"unexpected response to hangup: {resp!r}")
        return True

    async def reboot(self) -> bool:
        # 문서: "reboot now"는 확인 없이 재시작하며 별도 피드백을 반환하지 않는다.
        await self._send(cmd.REBOOT_NOW)
        return True

    async def get_calendar_status(self) -> str:
        resp = await self._call(cmd.CALENDARSTATUS_GET)
        if resp == "calendarstatus established":
            return "registered"
        if resp == "calendarstatus unavailable":
            return "not_registered"
        return "error"

    async def get_obtp_entries(self) -> list[CalendarEntry]:
        lines = await self._call_block(
            cmd.calendarmeetings_list(), "calendarmeetings list begin", "calendarmeetings list end"
        )
        entries: list[CalendarEntry] = []
        for line in lines:
            if not line.startswith("meeting|"):
                continue
            _, meeting_id, start, end, subject = line.split("|", 4)
            join_uri = await self._fetch_join_uri(meeting_id)
            entries.append(
                CalendarEntry(
                    subject=subject,
                    start_time=_normalize_poly_datetime(start),
                    end_time=_normalize_poly_datetime(end),
                    join_uri=join_uri,
                )
            )
        return entries

    async def _fetch_join_uri(self, meeting_id: str) -> str | None:
        info_lines = await self._call_block(
            cmd.calendarmeetings_info(meeting_id),
            "calendarmeetings info start",
            "calendarmeetings info end",
        )
        for line in info_lines:
            if line.startswith("dialingnumber|"):
                parts = line.split("|")
                if len(parts) >= 3:
                    return parts[2]
        return None

    async def join_meeting(self, entry: CalendarEntry) -> bool:
        if not entry.join_uri:
            raise DriverCommandError("meeting has no dialable join_uri")
        # dial()/hangup()/mute()는 이미 _call_expecting으로 응답 밀림에 대응하는데
        # join_meeting()만 예전 _call()을 그대로 쓰고 있었다 — direct-dial은 되는데
        # Teams 회의 링크 참가만 실패하던 원인(2026-07-31 VDI 2차 재테스트에서 확인,
        # 실패해도 예외 없이 False만 반환해 "실패: 200"으로만 보이고 원인 불명이었음).
        # 그런데 _call_expecting을 붙인 뒤에도 실장비에서 여전히 실패 — 원문을 보니
        # `dial phone sip "..."`(cmd.dial_phone)에 대해 장비가 "info: AUDIO call not
        # enabled"로 응답하고 있었다. 이건 응답이 밀린 잡음이 아니라 장비가 실제로
        # 거부한 것 — direct-dial(dial())이 쓰는 `dial manual`은 같은 주소로 정상
        # 동작하므로, join_meeting()도 dial_phone 대신 검증된 dial_manual을 쓰도록 변경.
        resp = await self._call_expecting(cmd.dial_manual(entry.join_uri), lambda line: line.startswith("dialing"))
        if not resp.startswith("dialing"):
            raise DriverCommandError(f"unexpected response to join: {resp!r}")
        return True


def _normalize_poly_datetime(raw: str) -> str:
    """Poly의 "YYYY-MM-DD:HH:MM" 타임스탬프를 Cisco(ISO 8601)와 비교 가능한
    "YYYY-MM-DDTHH:MM:00" 형태로 변환한다.

    두 벤더의 CalendarEntry.start_time/end_time은 JS 쪽에서 문자열 사전순
    비교(오늘 남은 회의 필터링, 정렬)에 그대로 쓰이는 공유 계약이다. Poly는
    날짜/시간 구분자로 ":"(0x3A)를, ISO는 "T"(0x54)를 쓰는데 ":"가 "T"보다
    아스키상 앞이라 Poly 회의는 항상 "이미 지난 회의"로 비교돼버린다 — 그래서
    드라이버 경계에서 정규화해 형태를 맞춘다. Poly는 타임존 오프셋을 보내지
    않으므로 오프셋/Z는 붙이지 않고(naive local-time) 초 단위(:00)만 채운다.
    """
    return raw.replace(":", "T", 1) + ":00"


_UPTIME_UNIT_SECONDS = {"day": 86400, "hour": 3600, "minute": 60, "second": 1}


def _parse_uptime(text: str) -> int | None:
    """Poly "uptime get" 응답("1 Hour, 10 Minutes" 형식)을 초로 환산한다.
    Day 단위 표기가 실제로 포함되는지는 문서에 예시가 없어 미확인 — Day/Hour/Minute/Second를
    느슨하게(대소문자 무관, 단수/복수 무관) 인식하고, 하나도 못 찾으면 None을 반환해
    상위 계층이 원문을 그대로 보여줄 수 있게 한다."""
    total = 0
    found = False
    for match in re.finditer(r"(\d+)\s*(day|hour|minute|second)s?", text, re.IGNORECASE):
        found = True
        value = int(match.group(1))
        unit = match.group(2).lower()
        total += value * _UPTIME_UNIT_SECONDS[unit]
    return total if found else None
