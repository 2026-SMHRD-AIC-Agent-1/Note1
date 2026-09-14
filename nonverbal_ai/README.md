# 연진 비언어 AI 파트

연진이 전달한 비언어 분석 파일을 `main` 브랜치에 보존한 폴더입니다.

## 파일
- `calibrate_from_webcam.py`: 웹캠/마이크 캘리브레이션 코드
- `nonverbal_analysis_v3.py`: 비언어 분석 원본 실행 래퍼
- `_source_parts/nonverbal_analysis_v3.part01.txt` ~ `part07.txt`: 연진이 전달한 `nonverbal_analysis_v3.py` 원문 조각

원본 분석 파일이 커서 업로드 과정에서 잘리지 않도록 조각으로 보존했고,
`nonverbal_analysis_v3.py`가 실행 시 조각을 순서대로 결합해 원본 코드를 실행합니다.

원본 `nonverbal_analysis_v3.py` SHA-256:
`623216ae2a2a814691e3401051f3ff730b0383052d03e6459cd6928b00a7a970`

현재 이 폴더는 연진이 전달한 코드를 보존하는 목적이며, 평가 기준/임계값 수정은 별도 검토 후 진행합니다.
