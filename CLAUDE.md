# Point SHP 검수 에이전트

## 프로젝트 목적
국토지리정보원 수령 시설 point SHP 자료를 전년도와 비교 검수하고 Word 보고서 생성.

## 검수 순서 (반드시 이 순서)
1. 시계열 수량 비교 (전년 vs 금년 폴더, 파일명 = 시설종류)
2. 중복 제거 (fac_nm + fac_add + x_coord + y_coord 모두 동일)
3. 지오코딩 정확도 (읍면동 경계 SHP 공간조인)
4. Word 보고서 생성

## SHP 컬럼 규격
- `fac_nm`: 시설명
- `fac_add`: 주소 (지번주소, 읍면동 추출 가능)
- `x_coord`: X좌표
- `y_coord`: Y좌표
- 좌표계: EPSG:5179 (Korea 2000 Unified CS)

## 파일 구조
- `agent.py`: 메인 에이전트
- `tools/count_compare.py`: 1단계 수량 비교
- `tools/duplicate.py`: 2단계 중복 탐지/제거
- `tools/geocode_check.py`: 3단계 지오코딩 정확도
- `tools/report.py`: Word 보고서 생성

## 실행
```bash
pip install -r requirements.txt
set ANTHROPIC_API_KEY=sk-ant-...
python agent.py
```

## 주의사항
- geopandas Windows 설치 문제 시: conda install geopandas 권장
- 읍면동 SHP 컬럼 자동감지 우선순위: EMD_NM > ADM_NM > 읍면동명 > EMD_KOR_NM
