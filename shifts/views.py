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

from .models import Task, Staff, UnavailableDate, Shift, AbsenceRequest
from .forms import StaffForm, TaskForm, AbsenceRequestForm
from .scheduler import generate_monthly_shifts, get_month_warnings

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
        
        # グリッド描画用にデータを整形: {date: {task_id: [shifts]}}
        grid_data = {d: {t.id: [] for t in tasks} for d in dates}
        for s in shifts:
            if s.date in grid_data and s.task_id in grid_data[s.date]:
                s.warning_list = warnings.get(s.id, [])
                grid_data[s.date][s.task_id].append(s)
                
        # テンプレートでループしやすいようにリストの入れ子に変換
        grid_rows = []
        for d in dates:
            cols = []
            for t in tasks:
                cols.append({
                    'task': t,
                    'shifts': grid_data[d][t.id],
                    'capable_staff': list(t.capable_staff.all())
                })
            grid_rows.append({
                'date': d,
                'cols': cols
            })

        context['grid_rows'] = grid_rows
        context['tasks'] = tasks
        context['year'] = year
        context['month'] = month
        
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

class AutoGenerateShiftView(AdminRequiredMixin, View):
    """シフト自動作成のトリガー"""
    def post(self, request):
        year = int(request.POST.get('year'))
        month = int(request.POST.get('month'))
        
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
        
        # 2. 勤務不可日の一覧
        unavailable_dates = set(
            UnavailableDate.objects.filter(
                staff=staff,
                date__range=(start_date, end_date)
            ).values_list('date', flat=True)
        )
        
        # 3. カレンダーの全セルデータを作成
        # カレンダー表示（週の始まりは月曜日）
        cal = calendar.Calendar(firstweekday=0)
        month_weeks = cal.monthdatescalendar(year, month)
        
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
                    'is_unavailable': d in unavailable_dates if is_current_month else False,
                    'absence': absence_map.get(d) if is_current_month else None,
                })
            calendar_weeks.append(week_days)
            
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
        
        return context

class ToggleUnavailableDateView(StaffRequiredMixin, View):
    """勤務不可日の登録・解除をトグルする"""
    def post(self, request):
        date_str = request.POST.get('date')
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        staff = request.user.staff_profile
        
        # すでに登録済みなら削除、未登録なら新規追加
        existing = UnavailableDate.objects.filter(staff=staff, date=target_date)
        if existing.exists():
            existing.delete()
            messages.success(request, f"{target_date} を勤務可能に戻しました。")
        else:
            # すでにシフトが入っている場合は警告を表示（登録は可能とする）
            has_shift = Shift.objects.filter(staff=staff, date=target_date).exists()
            UnavailableDate.objects.create(staff=staff, date=target_date)
            if has_shift:
                messages.warning(request, f"{target_date} を勤務不可に設定しました。※すでにこの日にシフトが割り当てられています。")
            else:
                messages.success(request, f"{target_date} を勤務不可に設定しました。")
                
        return redirect(f"{reverse('shifts:staff_dashboard')}?year={target_date.year}&month={target_date.month}")

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
