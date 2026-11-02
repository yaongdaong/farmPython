# gdd_calculator.py: 작물 생장에 필요한 적산온도(GDD, Growing Degree Days)를 계산하는 전용 로직 파일입니다.

def calculate_daily_gdd(t_max: float, t_min: float, base_temp: float, upper_temp: float) -> float:
    t_max = min(t_max, upper_temp)
    t_min = min(t_min, upper_temp)
    t_avg = (t_max + t_min) / 2.0
    daily_gdd = t_avg - base_temp
    return max(daily_gdd, 0.0)