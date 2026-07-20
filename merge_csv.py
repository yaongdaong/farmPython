# merge_csv.py
import os
import glob
import pandas as pd

def merge_farm_csv():
    # 🌟 [수정] 파일명 조건 없이 현재 폴더의 모든 .csv 파일을 싹 다 가져옵니다.
    csv_files = glob.glob("*.csv")
    
    # 만약 결과물인 agri_price_1year.csv가 이미 있다면 병합 대상에서 제외합니다 (중복 방지)
    csv_files = [f for f in csv_files if "agri_price_1year.csv" not in f]
    
    if not csv_files:
        print("❌ 에러: 폴더 안에서 어떤 CSV 파일도 찾지 못했습니다. 현재 명령어를 실행하는 위치를 다시 확인하세요.")
        return

    print(f"📦 총 {len(csv_files)}개의 CSV 파일을 발견했습니다. 병합 작업을 가동합니다...")
    
    combined_data = []
    
    for file in csv_files:
        try:
            # 윈도우 환경에서 다운받은 공공데이터는 대부분 cp949 인코딩입니다.
            df = pd.read_csv(file, encoding="cp949")
            combined_data.append(df)
            print(f"   -> [성공] {file} (행 수: {len(df)})")
        except Exception as e:
            try:
                # cp949로 실패하면 utf-8로 재시도
                df = pd.read_csv(file, encoding="utf-8")
                combined_data.append(df)
                print(f"   -> [성공(utf-8)] {file} (행 수: {len(df)})")
            except Exception as e2:
                print(f"   ⚠️ [실패] {file} 파일을 읽을 수 없습니다. (에러: {e2})")

    if not combined_data:
        print("❌ 에러: 읽어온 데이터가 비어있어 통합 파일을 생성할 수 없습니다.")
        return

    # 2. 하나의 데이터프레임으로 통합
    final_df = pd.concat(combined_data, ignore_index=True)
    
    # 3. Next.js와 FastAPI가 공유할 마스터 파일로 저장
    output_filename = "agri_price_1year.csv"
    final_df.to_csv(output_filename, index=False, encoding="utf-8-sig")
    
    print("\n==================================================")
    print(f"🎉 병합 완료! '{output_filename}' 파일이 생성되었습니다.")
    print(f"📊 총 집계된 데이터 수: {len(final_df)}건")
    print("==================================================")

if __name__ == "__main__":
    merge_farm_csv()