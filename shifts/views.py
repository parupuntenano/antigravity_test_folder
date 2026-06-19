import calendar
from datetime import date, datetime, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.views.generic import TemplateView, ListView, CreateView, UpdateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth import logout
from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.db.models import Count

from .models import Task, Staff, UnavailableDate, Shift, AbsenceRequest, AvailabilitySubmission, ShiftPublication
from .forms import StaffForm, TaskForm, AbsenceRequestForm
from .scheduler import generate_monthly_shifts, get_month_warnings


def check_weekly_availability(staff, year, month):
    """指定スタッフが指定月の全週で勤務不可日を2日以上設定しているか確認する。
    提出（AvailabilitySubmission）の有無は問わない。"""
    cal = calendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)
    for week in weeks:
        # その月に属する曜日のみを対象にする
        month_days = [d for d in week if d.month == month]
        if not month_days:
            continue
        count = UnavailableDate.objects.filter(
            staff=staff,
            date__in=month_days
        ).count()
        if count < 2:
            return False
    return True


# ==========================================
# 権限確認用ミックスイン
# ==========================================

class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """管理者のみアクセス可能にするミックスイン"""
    raise_exception = True
    def test_func(self):
        return hasattr(self.request.user, 'staff_profile') and self.request.user.staff_profile.role == 'admin'

class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """一般スタッフのみアクセス可能にするミックスイン"""
    raise_exception = True
    def test_func(self):
        return hasattr(self.request.user, 'staff_profile') and self.request.user.staff_profile.role == 'staff'

# ==========================================
# 認証関連ビュー
# ==========================================

class CustomLoginView(LoginView):
    template_name = 'shifts/login.html'
    
    def get_success_url(self):
        # ログイン後のリダイレクト先をロールごとに分岐
        user = self.request.user
        if hasattr(user, 'staff_profile'):
            if user.staff_profile.role == 'admin':
                return reverse('shifts:admin_dashboard')
            else:
                return reverse('shifts:staff_dashboard')
        if user.is_superuser:
            return reverse('shifts:admin_dashboard')
        return reverse('shifts:login')

class CustomLogoutView(View):
    def get(self, request):
        logout(request)
        return redirect('shifts:login')
    def post(self, request):
        logout(request)
        return redirect('shifts:login')

class DashboardDispatcher(LoginRequiredMixin, View):
    """ルートパス等でダッシュボードにアクセスした際の振り分け"""
    def get(self, request):
        user = request.user
        if hasattr(user, 'staff_profile'):
            if user.staff_profile.role == 'admin':
                return redirect('shifts:admin_dashboard')
            else:
                return redirect('shifts:staff_dashboard')
        if user.is_superuser:
            return redirect('shifts:admin_dashboard')
        return redirect('shifts:login')

# ==========================================
# 管理者用ビュー
# ==========================================

class AdminDashboardView(AdminRequiredMixin, TemplateView):
    template_name = 'shifts/admin_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = date.today()
        
        # ダッシュボード用の簡易統計
        context['staff_count'] = Staff.objects.filter(role='staff').count()
        context['task_count'] = Task.objects.count()
        context['pending_absences'] = AbsenceRequest.objects.filter(status='pending')
        
        # 今月の未割り当てシフトのカウント
        start_date = date(today.year, today.month, 1)
        _, num_days = calendar.monthrange(today.year, today.month)
        end_date = date(today.year, today.month, num_days)
        context['unassigned_shifts_count'] = Shift.objects.filter(
            date__range=(start_date, end_date),
            staff__isnull=True
        ).count()
        
        # 全スタッフの今月の提出状況をチェック
        total_staff = Staff.objects.filter(role='staff')
        submissions = AvailabilitySubmission.objects.filter(year=today.year, month=today.month)
        submitted_staff_ids = set(submissions.values_list('staff_id', flat=True))
        not_submitted_staff = total_staff.exclude(id__in=submitted_staff_ids)
        
        context['all_submitted'] = (not_submitted_staff.count() == 0)
        context['not_submitted_count'] = not_submitted_staff.count()
        
        context['year'] = today.year
        context['month'] = today.month
        return context

# スタッフ管理CRUD
class StaffListView(AdminRequiredMixin, ListView):
    model = Staff
    template_name = 'shifts/staff_list.html'
    context_object_name = 'staffs'
    
    def get_queryset(self):
        return Staff.objects.all().select_related('user').prefetch_related('available_tasks')

class StaffCreateView(AdminRequiredMixin, CreateView):
    model = Staff
    form_class = StaffForm
    template_name = 'shifts/staff_form.html'
    success_url = reverse_lazy('shifts:staff_list')
    
    def form_valid(self, form):
        messages.success(self.request, f"スタッフ「{form.cleaned_data['name']}」を登録しました。")
        return super().form_valid(form)

class StaffUpdateView(AdminRequiredMixin, UpdateView):
    model = Staff
    form_class = StaffForm
    template_name = 'shifts/staff_form.html'
    success_url = reverse_lazy('shifts:staff_list')
    
    def form_valid(self, form):
        messages.success(self.request, f"スタッフ「{form.cleaned_data['name']}」の情報を更新しました。")
        return super().form_valid(form)

class StaffDeleteView(AdminRequiredMixin, DeleteView):
    model = Staff
    template_name = 'shifts/staff_confirm_delete.html'
    success_url = reverse_lazy('shifts:staff_list')
    
    def post(self, request, *args, **kwargs):
        # 紐づくUserも一緒に削除する
        staff = self.get_object()
        user = staff.user
        name = staff.name
        response = super().post(request, *args, **kwargs)
        user.delete()
        messages.success(request, f"スタッフ「{name}」を削除しました。")
        return response

# 業務管理CRUD
class TaskListView(AdminRequiredMixin, ListView):
    model = Task
    template_name = 'shifts/task_list.html'
    context_object_name = 'tasks'

class TaskCreateView(AdminRequiredMixin, CreateView):
    model = Task
    form_class = TaskForm
    template_name = 'shifts/task_form.html'
    success_url = reverse_lazy('shifts:task_list')
    
    def form_valid(self, form):
        messages.success(self.request, f"業務「{form.cleaned_data['name']}」を登録しました。")
        return super().form_valid(form)

class TaskUpdateView(AdminRequiredMixin, UpdateView):
    model = Task
    form_class = TaskForm
    template_name = 'shifts/task_form.html'
    success_url = reverse_lazy('shifts:task_list')
    
    def form_valid(self, form):
        messages.success(self.request, f"業務「{form.cleaned_data['name']}」の情報を更新しました。")
        return super().form_valid(form)

class TaskDeleteView(AdminRequiredMixin, DeleteView):
    model = Task
    template_name = 'shifts/task_confirm_delete.html'
    success_url = reverse_lazy('shifts:task_list')
    
    def post(self, request, *args, **kwargs):
        task = self.get_object()
        name = task.name
        response = super().post(request, *args, **kwargs)
        messages.success(request, f"業務「{name}」を削除しました。")
        return response

# シフト一覧・手動調整・自動作成
class ShiftManagementView(AdminRequiredMixin, TemplateView):
    template_name = 'shifts/shift_grid.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # クエリパラメータから年月を取得（デフォルトは現在月）
        today = date.today()
        year = int(self.request.GET.get('year', today.year))
        month = int(self.request.GET.get('month', today.month))
        
        _, num_days = calendar.monthrange(year, month)
        dates = [date(year, month, d) for d in range(1, num_days + 1)]
        tasks = Task.objects.all()
        
        # 当月のシフトを一括取得
        shifts = Shift.objects.filter(
            date__range=(dates[0], dates[-1])
        ).select_related('staff', 'task')
        
        # 警告情報を一括取得
        warnings = get_month_warnings(year, month)
        
        # 提出不可日を一括取得
        unavailable_dates = set(
            UnavailableDate.objects.filter(
                date__range=(dates[0], dates[-1])
            ).values_list('staff_id', 'date')
        )
        
        # 当月のシフトをマッピング: (staff_id, date) -> shift
        shift_map = {}
        for s in shifts:
            if s.staff_id:
                shift_map[(s.staff_id, s.date)] = s
                
        # 警告情報をマッピング: (staff_id, date) -> [warnings]
        warnings_map = {}
        for s in shifts:
            if s.id in warnings:
                if s.staff_id:
                    if (s.staff_id, s.date) not in warnings_map:
                        warnings_map[(s.staff_id, s.date)] = []
                    warnings_map[(s.staff_id, s.date)].extend(warnings[s.id])

        # スタッフ一覧を取得（一般スタッフのみ）
        staffs = Staff.objects.filter(role='staff').prefetch_related('available_tasks')
        
        # グリッドの作成: スタッフごとの行
        grid_rows = []
        for staff in staffs:
            cols = []
            for d in dates:
                is_unavailable = (staff.id, d) in unavailable_dates
                assigned_shift = shift_map.get((staff.id, d))
                cell_warnings = warnings_map.get((staff.id, d), [])
                cols.append({
                    'date': d,
                    'is_unavailable': is_unavailable,
                    'assigned_shift': assigned_shift,
                    'warnings': cell_warnings,
                })
            grid_rows.append({
                'staff': staff,
                'cols': cols,
            })
            
        is_stage2 = shifts.exists()

        dates_with_info = []
        for d in dates:
            unassigned_tasks = [s.task.name for s in shifts if s.date == d and not s.staff_id]
            off_count = sum(1 for staff in staffs if (staff.id, d) in unavailable_dates)
            dates_with_info.append({
                'date': d,
                'unassigned_tasks': unassigned_tasks,
                'off_count': off_count,
            })

        context['grid_rows'] = grid_rows
        context['dates'] = dates
        context['dates_with_info'] = dates_with_info
        context['is_stage2'] = is_stage2
        context['tasks'] = tasks
        context['year'] = year
        context['month'] = month
        
        # 全スタッフの当月希望設定状況をチェック
        # 提出（AvailabilitySubmission）の有無に関わらず、週2日の勤務不可日が設定されていれば「準備完了」とみなす
        total_staff = Staff.objects.filter(role='staff')
        submissions = AvailabilitySubmission.objects.filter(year=year, month=month).select_related('staff')
        submitted_staff_ids = set(submissions.values_list('staff_id', flat=True))
        
        ready_staff = []       # 週2日の休み希望設定済み（提出済み含む）
        not_ready_staff = []   # まだ週2日未設定
        for s in total_staff:
            if check_weekly_availability(s, year, month):
                ready_staff.append(s)
            else:
                not_ready_staff.append(s)
        
        # 提出済みリストは従来どおり保持（スタッフ側の提出状況表示用）
        submitted_staff = [s for s in total_staff if s.id in submitted_staff_ids]
        not_submitted_staff = [s for s in total_staff if s.id not in submitted_staff_ids]
        
        context['submitted_staff'] = submitted_staff
        context['not_submitted_staff'] = not_submitted_staff
        context['ready_staff'] = ready_staff
        context['not_ready_staff'] = not_ready_staff
        context['all_submitted'] = (len(not_ready_staff) == 0)  # 全員週2日設定済みなら作成可能
        context['total_staff_count'] = len(total_staff)
        
        # シフト公開状況
        publication = ShiftPublication.objects.filter(year=year, month=month).first()
        context['publication'] = publication
        
        # 年月の選択肢（前後6ヶ月）
        month_choices = []
        start_choice = today - timedelta(days=180)
        for i in range(13):
            choice_date = start_choice + timedelta(days=30 * i)
            month_choices.append((choice_date.year, choice_date.month))
        # 重複排除とソート
        month_choices = sorted(list(set(month_choices)))
        context['month_choices'] = month_choices
        
        return context

    def post(self, request, *args, **kwargs):
        # クエリパラメータまたはPOSTパラメータから年月を取得
        year = int(request.GET.get('year', request.POST.get('year', date.today().year)))
        month = int(request.GET.get('month', request.POST.get('month', date.today().month)))
        
        stage = request.POST.get('stage')
        _, num_days = calendar.monthrange(year, month)
        dates = [date(year, month, d) for d in range(1, num_days + 1)]
        
        if stage == 'stage_1':
            # ===================================================
            # 第一段階（休日調整）の一括保存
            # ===================================================
            submitted_pairs = set()
            for val in request.POST.getlist('unavailable_dates'):
                try:
                    staff_id_str, date_str = val.split('_')
                    submitted_pairs.add((int(staff_id_str), datetime.strptime(date_str, '%Y-%m-%d').date()))
                except ValueError:
                    continue
            
            # 当月の既存の UnavailableDate を一括取得
            existing_unavailables = UnavailableDate.objects.filter(
                date__range=(dates[0], dates[-1])
            )
            existing_pairs = {(u.staff_id, u.date) for u in existing_unavailables}
            
            # データベースの更新
            to_delete_ids = []
            for u in existing_unavailables:
                if (u.staff_id, u.date) not in submitted_pairs:
                    to_delete_ids.append(u.id)
                    
            to_create = []
            staffs = Staff.objects.filter(role='staff')
            for staff in staffs:
                for d in dates:
                    pair = (staff.id, d)
                    if pair in submitted_pairs and pair not in existing_pairs:
                        to_create.append(UnavailableDate(staff=staff, date=d))
            
            from django.db import transaction
            with transaction.atomic():
                if to_delete_ids:
                    UnavailableDate.objects.filter(id__in=to_delete_ids).delete()
                if to_create:
                    UnavailableDate.objects.bulk_create(to_create)
                    
            messages.success(request, f"{year}年{month}月の休日希望（勤務不可日）を一括保存しました。")
            
        elif stage == 'stage_2':
            # ===================================================
            # 第二段階（業務割り当て）の一括保存
            # ===================================================
            staffs = list(Staff.objects.filter(role='staff'))
            
            # 各スタッフ・各日付に対する変更を収集
            # 1. まず現在のシフト割り当てをマップ化: (staff_id, date) -> shift
            shifts = Shift.objects.filter(date__range=(dates[0], dates[-1])).select_related('staff', 'task')
            shift_map = {}
            for s in shifts:
                if s.staff_id:
                    shift_map[(s.staff_id, s.date)] = s
                    
            # 変更対象の処理
            from django.db import transaction
            with transaction.atomic():
                # 送信された各組み合わせを処理
                for staff in staffs:
                    for d in dates:
                        input_name = f"task_{staff.id}_{d.strftime('%Y-%m-%d')}"
                        task_id_str = request.POST.get(input_name)
                        
                        current_shift = shift_map.get((staff.id, d))
                        current_task_id = current_shift.task_id if current_shift else None
                        
                        target_task_id = int(task_id_str) if task_id_str else None
                        
                        if current_task_id != target_task_id:
                            # 現在の割り当てを解除する
                            Shift.objects.filter(date=d, staff=staff).update(staff=None)
                            
                            if target_task_id:
                                task = get_object_or_404(Task, id=target_task_id)
                                # その日のそのタスクの未割り当てのスロットを探す
                                available_shift = Shift.objects.filter(date=d, task=task, staff__isnull=True).first()
                                if available_shift:
                                    available_shift.staff = staff
                                    available_shift.save()
                                else:
                                    # 空きがない場合は新規作成
                                    Shift.objects.create(
                                        date=d,
                                        task=task,
                                        staff=staff,
                                        status='draft'
                                    )
                                    
            messages.success(request, f"{year}年{month}月のシフト業務割り当てを一括保存しました。")
            
            # 公開済みの場合は「更新が必要」フラグを立てる
            pub = ShiftPublication.objects.filter(year=year, month=month).first()
            if pub and pub.is_published:
                pub.needs_update = True
                pub.save(update_fields=['needs_update'])
            
        return redirect(f"{reverse('shifts:shift_management')}?year={year}&month={month}")

class AutoGenerateShiftView(AdminRequiredMixin, View):
    """シフト自動作成のトリガー"""
    def post(self, request):
        year = int(request.POST.get('year'))
        month = int(request.POST.get('month'))
        
        # 週2日の勤務不可日が未設定のスタッフがいないか検証（提出有無は問わない）
        total_staff = Staff.objects.filter(role='staff')
        not_ready_staff = [s for s in total_staff if not check_weekly_availability(s, year, month)]
        
        if not_ready_staff:
            names = ", ".join([s.name for s in not_ready_staff])
            messages.error(request, f"週2日の休日希望が未設定のスタッフがいるため、シフト表を作成できません。未設定者: {names}")
            return redirect(f"{reverse('shifts:shift_management')}?year={year}&month={month}")
        
        success = generate_monthly_shifts(year, month)
        if success:
            messages.success(request, f"{year}年{month}月のシフトを自動作成しました。")
        else:
            messages.error(request, "シフトの作成に失敗しました。スタッフまたは業務が登録されているか確認してください。")
            
        return redirect(f"{reverse('shifts:shift_management')}?year={year}&month={month}")

class UpdateShiftStaffView(AdminRequiredMixin, View):
    """シフトスロットに対するスタッフの手動変更"""
    def post(self, request):
        shift_id = request.POST.get('shift_id')
        staff_id = request.POST.get('staff_id')
        shift = get_object_or_404(Shift, id=shift_id)
        
        if staff_id:
            staff = get_object_or_404(Staff, id=staff_id)
            shift.staff = staff
        else:
            shift.staff = None
            
        shift.save()
        messages.success(request, f"{shift.date}の{shift.task.name}の担当を変更しました。")
        
        return redirect(f"{reverse('shifts:shift_management')}?year={shift.date.year}&month={shift.date.month}")

class ReassignShiftView(AdminRequiredMixin, TemplateView):
    """急な休みなどの際の代替スタッフ再割り当て画面"""
    template_name = 'shifts/reassign.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        shift_id = self.kwargs.get('shift_id')
        shift = get_object_or_404(Shift, id=shift_id)
        
        # 1. 業務の担当可能スタッフ
        task = shift.task
        capable_staffs = list(task.capable_staff.all())
        
        # 2. その日の勤務不可日・休み申請を取得
        unavailable_staff_ids = set(
            UnavailableDate.objects.filter(date=shift.date).values_list('staff_id', flat=True)
        )
        absence_staff_ids = set(
            AbsenceRequest.objects.filter(date=shift.date, status='approved').values_list('staff_id', flat=True)
        )
        exclude_staff_ids = unavailable_staff_ids.union(absence_staff_ids)
        
        # 3. その日すでに別の業務に入っているスタッフを取得
        already_working_ids = set(
            Shift.objects.filter(date=shift.date).exclude(id=shift.id).values_list('staff_id', flat=True)
        )
        exclude_staff_ids = exclude_staff_ids.union(already_working_ids)
        
        # 4. 今月のシフト回数をカウント
        start_date = date(shift.date.year, shift.date.month, 1)
        _, num_days = calendar.monthrange(shift.date.year, shift.date.month)
        end_date = date(shift.date.year, shift.date.month, num_days)
        
        shift_counts = {
            row['staff_id']: row['count']
            for row in Shift.objects.filter(
                date__range=(start_date, end_date),
                staff__isnull=False
            ).values('staff_id').annotate(count=Count('id'))
        }
        
        # 5. 前日と同じ業務に入っているか（連続勤務判定）
        day_before = shift.date - timedelta(days=1)
        consecutive_staff_ids = set(
            Shift.objects.filter(date=day_before, task=task).values_list('staff_id', flat=True)
        )
        
        # 代替候補スタッフリストの組み立て
        candidates = []
        for staff in capable_staffs:
            if staff.id in exclude_staff_ids:
                continue
                
            is_consecutive = staff.id in consecutive_staff_ids
            month_count = shift_counts.get(staff.id, 0)
            
            candidates.append({
                'staff': staff,
                'month_count': month_count,
                'is_consecutive': is_consecutive,
            })
            
        # シフト数が少なく、かつ連続勤務ではないスタッフを優先してソート
        candidates.sort(key=lambda x: (1 if x['is_consecutive'] else 0, x['month_count']))
        
        context['shift'] = shift
        context['candidates'] = candidates
        return context

    def post(self, request, *args, **kwargs):
        shift_id = self.kwargs.get('shift_id')
        staff_id = request.POST.get('staff_id')
        shift = get_object_or_404(Shift, id=shift_id)
        
        if staff_id:
            staff = get_object_or_404(Staff, id=staff_id)
            shift.staff = staff
        else:
            shift.staff = None
            
        shift.save()
        messages.success(request, f"{shift.date}の{shift.task.name}に「{shift.staff.name if shift.staff else '未割り当て'}」を再割り当てしました。")
        return redirect(f"{reverse('shifts:shift_management')}?year={shift.date.year}&month={shift.date.month}")

class AbsenceRequestApprovalView(AdminRequiredMixin, View):
    """管理者による休み申請の承認・却下"""
    def post(self, request, request_id):
        action = request.POST.get('action') # 'approve' or 'reject'
        abs_req = get_object_or_404(AbsenceRequest, id=request_id)
        
        if action == 'approve':
            abs_req.status = 'approved'
            abs_req.save()
            
            # 承認された場合、該当日のそのスタッフのシフト割り当てを解除（空欄にする）
            matching_shifts = Shift.objects.filter(date=abs_req.date, staff=abs_req.staff)
            count = matching_shifts.count()
            if count > 0:
                for s in matching_shifts:
                    s.staff = None
                    s.save()
                messages.success(request, f"休み申請を承認しました。担当していた{count}件のシフトを解除しました。再割り当てを行ってください。")
            else:
                messages.success(request, "休み申請を承認しました。")
        elif action == 'reject':
            abs_req.status = 'rejected'
            abs_req.save()
            messages.success(request, "休み申請を却下しました。")
            
        return redirect('shifts:admin_dashboard')

# ==========================================
# スタッフ用ビュー
# ==========================================

class StaffDashboardView(StaffRequiredMixin, TemplateView):
    template_name = 'shifts/staff_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        staff = self.request.user.staff_profile
        today = date.today()
        
        year = int(self.request.GET.get('year', today.year))
        month = int(self.request.GET.get('month', today.month))
        
        _, num_days = calendar.monthrange(year, month)
        start_date = date(year, month, 1)
        end_date = date(year, month, num_days)
        
        # 1. 自分の当月シフト一覧
        my_shifts = Shift.objects.filter(
            staff=staff,
            date__range=(start_date, end_date)
        ).select_related('task')
        
        # カレンダー描画用に日付キーのマッピング
        shift_map = {s.date: s for s in my_shifts}
        
        # 3. カレンダーの全セルデータを作成
        # カレンダー表示（週の始まりは月曜日）
        cal = calendar.Calendar(firstweekday=0)
        month_weeks = cal.monthdatescalendar(year, month)
        
        # 2. 勤務不可日の一覧 (カレンダー表示範囲全体で取得)
        calendar_unavailable_dates = set(
            UnavailableDate.objects.filter(
                staff=staff,
                date__range=(month_weeks[0][0], month_weeks[-1][-1])
            ).values_list('date', flat=True)
        )
        
        # 4. 急な休み申請の一覧
        absence_requests = AbsenceRequest.objects.filter(
            staff=staff,
            date__range=(start_date, end_date)
        )
        absence_map = {ar.date: ar for ar in absence_requests}
        
        # 週ごとのカレンダーデータ整形
        calendar_weeks = []
        for week in month_weeks:
            week_days = []
            for d in week:
                is_current_month = (d.month == month and d.year == year)
                week_days.append({
                    'date': d,
                    'is_current_month': is_current_month,
                    'shift': shift_map.get(d) if is_current_month else None,
                    'is_unavailable': d in calendar_unavailable_dates,
                    'absence': absence_map.get(d) if is_current_month else None,
                })
            # その週の不可日カウント
            weekly_unavailable_count = sum(1 for day in week_days if day['is_unavailable'])
            calendar_weeks.append({
                'days': week_days,
                'unavailable_count': weekly_unavailable_count,
                'is_ok': weekly_unavailable_count == 2,
                'remaining': 2 - weekly_unavailable_count,
            })
            
        context['calendar_weeks'] = calendar_weeks
        context['year'] = year
        context['month'] = month
        context['staff'] = staff
        context['absence_form'] = AbsenceRequestForm()
        
        # 休み申請履歴
        context['my_absence_requests'] = AbsenceRequest.objects.filter(staff=staff).order_by('-date')[:10]
        
        # 前月・翌月の計算
        prev_month_date = start_date - timedelta(days=1)
        next_month_date = end_date + timedelta(days=1)
        context['prev_year'] = prev_month_date.year
        context['prev_month'] = prev_month_date.month
        context['next_year'] = next_month_date.year
        context['next_month'] = next_month_date.month
        
        # 提出状況の取得
        submitted = AvailabilitySubmission.objects.filter(
            staff=staff,
            year=year,
            month=month
        ).exists()
        context['is_submitted'] = submitted
        
        # シフト公開状況の取得
        publication = ShiftPublication.objects.filter(year=year, month=month).first()
        context['publication'] = publication
        context['shift_is_published'] = publication is not None and publication.is_published
        
        return context

class ToggleUnavailableDateView(StaffRequiredMixin, View):
    """勤務不可日の登録・解除をトグルする"""
    def post(self, request):
        date_str = request.POST.get('date')
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        staff = request.user.staff_profile
        
        # すでに希望提出済みの場合はエラーを表示してリダイレクト
        submitted = AvailabilitySubmission.objects.filter(
            staff=staff,
            year=target_date.year,
            month=target_date.month
        ).exists()
        if submitted:
            messages.error(request, f"{target_date.year}年{target_date.month}月の希望は既に提出されているため、変更できません。")
            return redirect(f"{reverse('shifts:staff_dashboard')}?year={target_date.year}&month={target_date.month}")
        
        # target_dateが入る週（月〜日）の範囲を取得
        start_of_week = target_date - timedelta(days=target_date.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        
        # すでに登録済みなら削除、未登録なら新規追加
        existing = UnavailableDate.objects.filter(staff=staff, date=target_date)
        if existing.exists():
            existing.delete()
            messages.success(request, f"{target_date} を勤務可能に戻しました。")
        else:
            # その週に登録されている勤務不可日の数を取得
            weekly_count = UnavailableDate.objects.filter(
                staff=staff,
                date__range=(start_of_week, end_of_week)
            ).count()
            
            if weekly_count >= 2:
                messages.error(request, f"{start_of_week}の週には、すでに勤務不可日が2日登録されています。週に登録できる勤務不可日は2日までです。")
            else:
                # すでにシフトが入っている場合は警告を表示（登録は可能とする）
                has_shift = Shift.objects.filter(staff=staff, date=target_date).exists()
                UnavailableDate.objects.create(staff=staff, date=target_date)
                if has_shift:
                    messages.warning(request, f"{target_date} を勤務不可に設定しました。※すでにこの日にシフトが割り当てられています。")
                else:
                    messages.success(request, f"{target_date} を勤務不可に設定しました。")
                
        return redirect(f"{reverse('shifts:staff_dashboard')}?year={target_date.year}&month={target_date.month}")

class SubmitAvailabilityView(StaffRequiredMixin, View):
    """スタッフが月間の希望提出を行うビュー"""
    def post(self, request):
        year = int(request.POST.get('year'))
        month = int(request.POST.get('month'))
        staff = request.user.staff_profile
        
        # すでに提出済みかチェック
        if AvailabilitySubmission.objects.filter(staff=staff, year=year, month=month).exists():
            messages.warning(request, f"{year}年{month}月の希望はすでに提出されています。")
            return redirect(f"{reverse('shifts:staff_dashboard')}?year={year}&month={month}")
        
        # カレンダーの週ごとの不可日数チェック
        cal = calendar.Calendar(firstweekday=0)
        month_weeks = cal.monthdatescalendar(year, month)
        
        for week in month_weeks:
            weekly_count = UnavailableDate.objects.filter(
                staff=staff,
                date__range=(week[0], week[-1])
            ).count()
            
            if weekly_count != 2:
                messages.error(request, f"{week[0]}の週の勤務不可日が{weekly_count}日しか設定されていません。各週に必ず2日設定してください。")
                return redirect(f"{reverse('shifts:staff_dashboard')}?year={year}&month={month}")
        
        # 提出データを登録
        AvailabilitySubmission.objects.create(staff=staff, year=year, month=month)
        messages.success(request, f"{year}年{month}月の希望を提出しました。")
        return redirect(f"{reverse('shifts:staff_dashboard')}?year={year}&month={month}")

class SubmitAbsenceRequestView(StaffRequiredMixin, View):
    """スタッフからの急な休み申請の提出"""
    def post(self, request):
        form = AbsenceRequestForm(request.POST)
        if form.is_valid():
            absence = form.save(commit=False)
            absence.staff = request.user.staff_profile
            absence.status = 'pending'
            
            # 既に申請があるかチェック
            existing = AbsenceRequest.objects.filter(staff=absence.staff, date=absence.date)
            if existing.exists():
                messages.error(request, f"{absence.date} にはすでに休み申請が提出されています。")
            else:
                absence.save()
                messages.success(request, f"{absence.date} の急な休み申請を提出しました（承認待ち）。")
        else:
            messages.error(request, "申請内容に不備があります。日付を正しく指定してください。")
            
        return redirect('shifts:staff_dashboard')

class ShiftStatsView(AdminRequiredMixin, TemplateView):
    """管理者用：スタッフの勤務日数集計ページ"""
    template_name = 'shifts/shift_stats.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # クエリパラメータから年月を取得（デフォルトは現在月）
        today = date.today()
        year = int(self.request.GET.get('year', today.year))
        month = int(self.request.GET.get('month', today.month))
        
        _, num_days = calendar.monthrange(year, month)
        dates = [date(year, month, d) for d in range(1, num_days + 1)]
        
        # 当月のシフトを一括取得
        shifts = Shift.objects.filter(
            date__range=(dates[0], dates[-1])
        ).select_related('staff')
        
        # スタッフごとのシフト勤務日数・勤務不可日数の集計
        staff_list = Staff.objects.filter(role='staff').prefetch_related('available_tasks')
        
        # スタッフごとの当月シフト回数
        staff_shift_counts = {st.id: 0 for st in staff_list}
        for s in shifts:
            if s.staff and s.staff.id in staff_shift_counts:
                staff_shift_counts[s.staff.id] += 1
                
        # スタッフごとの当月勤務不可日数（UnavailableDate と承認済み AbsenceRequest の重複を排除）
        unavailable_dates_by_staff = {st.id: set() for st in staff_list}
        
        unavailables = UnavailableDate.objects.filter(
            staff__in=staff_list,
            date__range=(dates[0], dates[-1])
        )
        for u in unavailables:
            if u.staff_id in unavailable_dates_by_staff:
                unavailable_dates_by_staff[u.staff_id].add(u.date)
                
        absences = AbsenceRequest.objects.filter(
            staff__in=staff_list,
            date__range=(dates[0], dates[-1]),
            status='approved'
        )
        for a in absences:
            if a.staff_id in unavailable_dates_by_staff:
                unavailable_dates_by_staff[a.staff_id].add(a.date)
                
        # 全体平均シフト回数の算出
        total_shifts = sum(staff_shift_counts.values())
        num_staff = len(staff_list)
        average_shifts = round(total_shifts / num_staff, 1) if num_staff > 0 else 0
        
        staff_stats = []
        for st in staff_list:
            sc = staff_shift_counts[st.id]
            diff = round(sc - average_shifts, 1)
            diff_str = f"+{diff}" if diff > 0 else f"{diff}"
            if diff == 0:
                diff_str = "±0"
            staff_stats.append({
                'id': st.id,
                'name': st.name,
                'available_tasks_count': st.available_tasks.count(),
                'shift_count': sc,
                'unavailable_count': len(unavailable_dates_by_staff[st.id]),
                'diff': diff_str,
                'diff_value': diff,
                'percentage': round(sc / num_days * 100) if num_days > 0 else 0,
            })
            
        # シフト回数が多い順にソート
        staff_stats.sort(key=lambda x: x['shift_count'], reverse=True)
        
        context['staff_stats'] = staff_stats
        context['average_shifts'] = average_shifts
        context['year'] = year
        context['month'] = month
        
        # 年月の選択肢（前後6ヶ月）
        month_choices = []
        start_choice = today - timedelta(days=180)
        for i in range(13):
            choice_date = start_choice + timedelta(days=30 * i)
            month_choices.append((choice_date.year, choice_date.month))
        month_choices = sorted(list(set(month_choices)))
        context['month_choices'] = month_choices
        
        return context

class AdminToggleUnavailableDateView(AdminRequiredMixin, View):
    """管理者がスタッフの勤務不可日をトグルする"""
    def post(self, request):
        staff_id = request.POST.get('staff_id')
        date_str = request.POST.get('date')
        
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        staff = get_object_or_404(Staff, id=staff_id)
        
        existing = UnavailableDate.objects.filter(staff=staff, date=target_date)
        if existing.exists():
            existing.delete()
            messages.success(request, f"{staff.name} の {target_date} を勤務可能に設定しました。")
        else:
            UnavailableDate.objects.create(staff=staff, date=target_date)
            messages.success(request, f"{staff.name} の {target_date} を勤務不可に設定しました。")
            
        return redirect(f"{reverse('shifts:shift_management')}?year={target_date.year}&month={target_date.month}")

class AdminUpdateShiftView(AdminRequiredMixin, View):
    """スタッフの特定日のタスク割り当てを変更する"""
    def post(self, request):
        staff_id = request.POST.get('staff_id')
        date_str = request.POST.get('date')
        task_id = request.POST.get('task_id') # empty means unassigned
        
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        staff = get_object_or_404(Staff, id=staff_id)
        
        # 1. まずその日のこのスタッフの割り当てを解除する
        Shift.objects.filter(date=target_date, staff=staff).update(staff=None)
        
        # 2. 新しいタスクが指定された場合
        if task_id:
            task = get_object_or_404(Task, id=task_id)
            # その日にそのタスクの未割り当てのスロットがあるか探す
            available_shift = Shift.objects.filter(date=target_date, task=task, staff__isnull=True).first()
            if available_shift:
                available_shift.staff = staff
                available_shift.save()
            else:
                # 空きスロットがない場合は新規作成する
                Shift.objects.create(
                    date=target_date,
                    task=task,
                    staff=staff,
                    status='draft'
                )
            messages.success(request, f"{staff.name} を {target_date} の「{task.name}」に割り当てました。")
        else:
            messages.success(request, f"{staff.name} の {target_date} の割り当てを解除しました。")
            
        return redirect(f"{reverse('shifts:shift_management')}?year={target_date.year}&month={target_date.month}")

class ClearMonthlyShiftsView(AdminRequiredMixin, View):
    """シフト表をクリアして休日調整に戻る"""
    def post(self, request):
        year = int(request.POST.get('year'))
        month = int(request.POST.get('month'))
        
        start_date = date(year, month, 1)
        _, num_days = calendar.monthrange(year, month)
        end_date = date(year, month, num_days)
        
        from django.db import transaction
        with transaction.atomic():
            Shift.objects.filter(date__range=(start_date, end_date)).delete()
            # シフトをクリアするので公開状態もリセット
            ShiftPublication.objects.filter(year=year, month=month).delete()
        
        messages.success(request, f"{year}年{month}月のシフトをクリアし、第一段階（休日調整）に戻しました。")
        return redirect(f"{reverse('shifts:shift_management')}?year={year}&month={month}")


class PublishShiftsView(AdminRequiredMixin, View):
    """月次シフトをスタッフに公開・更新する"""
    def post(self, request):
        year = int(request.POST.get('year'))
        month = int(request.POST.get('month'))
        
        from django.utils import timezone
        pub, _ = ShiftPublication.objects.get_or_create(year=year, month=month)
        pub.published_at = timezone.now()
        pub.needs_update = False
        pub.save()
        
        messages.success(request, f"{year}年{month}月のシフトをスタッフに公開しました。")
        return redirect(f"{reverse('shifts:shift_management')}?year={year}&month={month}")
