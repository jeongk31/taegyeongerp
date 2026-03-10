from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


def kst_now():
    """현재 한국 시간 (datetime)"""
    return datetime.now(KST)


def kst_today():
    """오늘 날짜 한국 시간 기준 (date)"""
    return datetime.now(KST).date()
