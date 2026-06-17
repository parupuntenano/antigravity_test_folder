import calendar
import random
from datetime import date, timedelta
from django.db import transaction
from .models import Task, Staff, UnavailableDate, AbsenceRequest, Shift

def generate_monthly_shifts(year, month):
    """
    指定された年月に対して、シフトを自動作成する。
    1. 既存の下書きシフトを削除する。
    2. 必要人数分の空スロットを作成する。
    3. 公平性と連続勤務の回避を考慮してスタッフを割り当てる。
    """
    _, num_days = calendar.monthrange(year, month)
    start_date = date(year, month, 1)
    end_date = date(year, month, num_days)

    with transaction.atomic():
        # 既存の下書き（かつ確定していない）シフトを削除
        # 本システムでは、再作成時は月全体のシフトを一度クリアして作成し直す
        Shift.objects.filter(date__range=(start_date, end_date)).delete()

        tasks = list(Task.objects.all())
        staff_pool = list(Staff.objects.filter(role='staff').prefetch_related('available_tasks'))

        if not tasks or not staff_pool:
            return False

        # 勤務不可日と承認された休み申請を一括取得してセット化
        unavailable_dates = UnavailableDate.objects.filter(date__range=(start_date, end_date))
        absence_requests = AbsenceRequest.objects.filter(date__range=(start_date, end_date), status='approved')

        unavailable_set = set()
        for ud in unavailable_dates:
            unavailable_set.add((ud.staff_id, ud.date))
        for ar in absence_requests:
            unavailable_set.add((ar.staff_id, ar.date))

        # 各スタッフの今月の割り当て回数
        staff_shift_counts = {staff.id: 0 for staff in staff_pool}

        # 前日の最終割り当て業務を保持する辞書
        last_assigned_task = {staff.id: None for staff in staff_pool}

        # 月の初日の前日に割り当てられていた業務を取得して初期化
        day_before = start_date - timedelta(days=1)
        prev_shifts = Shift.objects.filter(date=day_before)
        for ps in prev_shifts:
            if ps.staff_id and ps.staff_id in last_assigned_task:
                last_assigned_task[ps.staff_id] = ps.task_id

        # 日付ごとに割り当てを行う
        for day in range(1, num_days + 1):
            current_date = date(year, month, day)
            assigned_today = set()

            # タスクごとにループ
            # 割り当て可能なスタッフが少ないタスクから順に割り当てると破綻しにくいため、
            # 担当可能スタッフ数で昇順ソートする
            tasks.sort(key=lambda t: t.capable_staff.count())

            for task in tasks:
                required = task.required_people_per_day
                
                # 必要な人数分スロットを作成して埋めていく
                for _ in range(required):
                    # 候補者のリストアップ
                    candidates = []
                    for staff in staff_pool:
                        # 1. その日の業務が担当可能か
                        if not staff.available_tasks.filter(id=task.id).exists():
                            continue
                        # 2. 勤務不可日または承認された休みではないか
                        if (staff.id, current_date) in unavailable_set:
                            continue
                        # 3. 本日すでに別の業務に割り当てられていないか
                        if staff.id in assigned_today:
                            continue
                        
                        candidates.append(staff)

                    if candidates:
                        # スコア計算
                        # - 前日と同じ業務だった場合、ペナルティを加算（連続勤務回避）
                        # - 今月のこれまでのシフト回数（偏り防止）
                        # - タイブレークのための少量のランダム値
                        candidate_scores = []
                        for c in candidates:
                            penalty = 100 if last_assigned_task[c.id] == task.id else 0
                            # 今月のシフト数が少ない人を最優先にする
                            score = penalty + c.id * 0.001  # 基本の決定性
                            # シフト数による傾斜
                            score += staff_shift_counts[c.id] * 5
                            # わずかなランダム要素を加えて毎回の自動作成に多様性を持たせる
                            score += random.uniform(0, 0.1)
                            candidate_scores.append((score, c))

                        # スコアが低い順にソートして、最も適したスタッフを採用
                        candidate_scores.sort(key=lambda x: x[0])
                        chosen_staff = candidate_scores[0][1]

                        # シフトの作成
                        Shift.objects.create(
                            date=current_date,
                            task=task,
                            staff=chosen_staff,
                            status='draft'
                        )
                        assigned_today.add(chosen_staff.id)
                        staff_shift_counts[chosen_staff.id] += 1
                        last_assigned_task[chosen_staff.id] = task.id
                    else:
                        # 割り当て可能なスタッフがいない場合は、未割り当てとしてスロットだけ作成
                        Shift.objects.create(
                            date=current_date,
                            task=task,
                            staff=None,
                            status='draft'
                        )

            # 本日割り当てがなかったスタッフの「前回の業務」をクリアする
            for staff in staff_pool:
                if staff.id not in assigned_today:
                    last_assigned_task[staff.id] = None

    return True


def get_month_warnings(year, month):
    """
    指定された年月の全シフトに対する警告を一括で取得する。
    戻り値: {shift_id: [warning_messages]}
    """
    _, num_days = calendar.monthrange(year, month)
    start_date = date(year, month, 1)
    end_date = date(year, month, num_days)

    # 1日前のシフトも含めて取得（連続勤務の判定のため）
    day_before = start_date - timedelta(days=1)
    shifts = Shift.objects.filter(date__range=(day_before, end_date)).select_related('staff', 'task')

    # 勤務不可日の一括取得
    unavailable_dates = UnavailableDate.objects.filter(date__range=(start_date, end_date))
    unavailable_set = {(ud.staff_id, ud.date) for ud in unavailable_dates}

    # 休み申請の一括取得
    absence_requests = AbsenceRequest.objects.filter(date__range=(start_date, end_date), status='approved')
    absence_set = {(ar.staff_id, ar.date) for ar in absence_requests}

    # 日付ごとのスタッフ割り当て状況をマップ化: (staff_id, date) -> task_id
    assignment_map = {}
    for s in shifts:
        if s.staff_id:
            assignment_map[(s.staff_id, s.date)] = s.task_id

    warnings = {}
    for s in shifts:
        # 1日前のシフトは警告対象外（表示されないため）
        if s.date < start_date:
            continue

        shift_warnings = []
        if not s.staff:
            shift_warnings.append("スタッフが未割り当てです。")
        else:
            # 勤務不可日のチェック
            if (s.staff_id, s.date) in unavailable_set:
                shift_warnings.append("勤務不可日に割り当てられています。")
            if (s.staff_id, s.date) in absence_set:
                shift_warnings.append("急な休み（承認済み）の日に割り当てられています。")

            # 連続勤務のチェック
            prev_date = s.date - timedelta(days=1)
            prev_task_id = assignment_map.get((s.staff_id, prev_date))
            if prev_task_id == s.task_id:
                shift_warnings.append(f"同じ業務（{s.task.name}）が連続しています。")

        if shift_warnings:
            warnings[s.id] = shift_warnings

    return warnings
