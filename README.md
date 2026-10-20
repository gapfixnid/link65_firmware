# Link65 Studio Firmware

Owlab Link65 Hotswap용 독립 펌웨어 프로젝트입니다. 현재 버전은 **v1.0.2-rc1**이며 VIA에서는 `1.0.2`로 표시됩니다. 설정 웹 프로젝트는 [link65_setting](https://github.com/gapfixnid/link65_setting)에서 별도로 관리합니다.

## 구성

- `overlays/`: 실제 빌드에 사용한 키맵, 설정, 링커 스크립트와 타이머 변경 소스.
- `vendor-lock.json`: QMK와 필요한 라이브러리의 커밋, 다운로드 주소, SHA-256.
- `releases/v1.0.2-rc1/`: 기기에 기록하고 다시 읽어 일치를 확인한 BIN/ELF 및 이미지 명세.
- `tools/`: 소스 준비, 빌드, 에뮬레이션 검증, 명시적으로 실행하는 업데이트 도구.
- `tests/fixtures/`: 개인정보가 없는 기존 v1.0.1 빌드 이미지.
- `docs/validation/`: 합성 입력 검증 결과와 개인정보를 제외한 기기 적용 결과.

QMK 원본과 툴체인은 캐시로 준비하며 Git에 중복 저장하지 않습니다. 변경할 소스는 `overlays/`에서 편집합니다. 설정 페이지나 기존 데스크톱 프로그램의 폴더 없이 빌드·오프라인 검증이 가능합니다.

## 빌드

Windows에서 Python 3.13을 준비한 뒤 저장소 루트에서 실행합니다.

```powershell
python tools/setup.py
python -m pip install -r requirements-dev.txt
python tools/build.py --verify
```

준비 스크립트는 고정된 소스와 QMK MSYS 1.12.0을 검증 후 로컬에 추출합니다. 설치 프로그램 실행, 전역 PATH 변경, 장치 통신은 하지 않습니다. 결과는 `.build/current/`에 생성됩니다. Linux/macOS에서는 `--sources-only`로 소스를 준비하고 해당 OS의 QMK 빌드 의존성을 별도로 설치해야 합니다. 실제 재현 빌드는 Windows에서 확인했습니다.

이미 추출한 QMK MSYS가 있다면 `python tools/setup.py --sources-only` 후 `python tools/build.py --toolchain <{app} 폴더> --verify`를 사용할 수 있습니다. `--require-release-match`는 생성한 BIN이 저장된 릴리스와 바이트 단위로 같은지도 확인합니다.

## 오프라인 검증

```powershell
python -m pip install -r requirements-dev.txt
python tools/test_update_guard.py
python tools/verify_timer.py
```

기본 검증은 저장된 릴리스 BIN/ELF를 사용하므로 컴파일러나 다른 프로젝트가 필요하지 않습니다. CI도 이 릴리스 회귀 검증을 수행하며 소스의 새 컴파일은 별도 빌드 단계입니다. 빌드 명령의 `--verify`는 새로 생성한 이미지에 대해 같은 검증을 수행합니다.

타이머 9,433쌍, 디바운스 입력 추적 104쌍, 키 동작 추적 56쌍에서 v1.0.1과 결과가 일치했습니다. 실제 접점 튐, 67개 물리 스위치의 전기적 동작, 접점부터 PC까지의 지연 단축량을 측정한 결과는 아닙니다.

## 기기와 설정 호환성

키별 대칭 지연 디바운스 5ms, USB 전송 간격 1ms, VIA 13, QMK 키코드 0.0.9를 사용합니다. 4레이어·16매크로·1407바이트 버퍼를 유지합니다. 타이머 변환만 같은 올림 결과의 32비트 연산으로 경량화했고 내부 100kHz tick 설정은 유지했습니다. 자세한 내용은 [프로토콜 명세](docs/protocol.md)를 참고하세요.

현재 릴리스의 SHA-256:

```text
c33fdae03fe7e41e358c69ca560c54299c52e1d5d9b4a0cd95017332ac148285
```

애플리케이션은 `0x08006000..0x0800EFFF`입니다. 기존 부트로더와 설정 Flash는 기록 범위에서 제외합니다. 업데이트는 현재 설정을 먼저 백업한 뒤 진행해야 하며 `tools/update_firmware.py`는 기본적으로 조회만 하고 `--flash`를 명시해야 기록합니다. 지원하지 않는 이미지 해시, DFU 기기 누락·복수 감지·잘못된 alternate는 거절합니다. 명령 진입은 지원하지 않으며 USB 분리 → B 키를 누른 채 USB 연결 → B 키 놓기로 DFU에 진입합니다. 전송 성공 후 이미지 재조회와 일반 모드 설정 확인이 필요합니다.

사용자 설정 백업, 실제 기기 Flash 덤프, USB 식별 정보는 이 저장소에 포함하지 않습니다. 기존 작업 폴더의 장치별 백업은 별도로 보존합니다.

## 라이선스

프로젝트 변경 코드는 GPL v3로 배포합니다. QMK 및 각 라이브러리의 기존 저작권·라이선스 표기를 유지합니다. `licenses/QMK-LICENSE`와 다운로드한 각 라이브러리의 라이선스도 확인하세요. 고정된 원본 전체와 이 저장소의 오버레이·빌드 도구가 해당 릴리스의 재현 가능한 소스를 구성합니다.
