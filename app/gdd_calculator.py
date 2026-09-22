# app/gdd_calculator.py
def calculate_daily_gdd(t_max: float, t_min: float, base_temp: float, upper_temp: float) -> float:
    t_max = min(t_max, upper_temp)
    t_min = min(t_min, upper_temp)
    t_avg = (t_max + t_min) / 2.0
    daily_gdd = t_avg - base_temp
    return max(daily_gdd, 0.0)