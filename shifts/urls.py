from django.urls import path
from django.views.generic import TemplateView
from . import views

app_name = 'shifts'

urlpatterns = [
    # PWA関連ファイル
    path('manifest.json', TemplateView.as_view(template_name='shifts/manifest.json', content_type='application/json'), name='manifest'),
    path('sw.js', TemplateView.as_view(template_name='shifts/sw.js', content_type='application/javascript'), name='service_worker'),

    # 認証とダッシュボード振り分け
    path('', views.DashboardDispatcher.as_view(), name='dashboard'),
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', views.CustomLogoutView.as_view(), name='logout'),

    # 管理者用
    path('manager/dashboard/', views.AdminDashboardView.as_view(), name='admin_dashboard'),
    
    # スタッフ管理
    path('manager/staff/', views.StaffListView.as_view(), name='staff_list'),
    path('manager/staff/new/', views.StaffCreateView.as_view(), name='staff_create'),
    path('manager/staff/<int:pk>/edit/', views.StaffUpdateView.as_view(), name='staff_edit'),
    path('manager/staff/<int:pk>/delete/', views.StaffDeleteView.as_view(), name='staff_delete'),
    
    # 業務管理
    path('manager/tasks/', views.TaskListView.as_view(), name='task_list'),
    path('manager/tasks/new/', views.TaskCreateView.as_view(), name='task_create'),
    path('manager/tasks/<int:pk>/edit/', views.TaskUpdateView.as_view(), name='task_edit'),
    path('manager/tasks/<int:pk>/delete/', views.TaskDeleteView.as_view(), name='task_delete'),
    
    # シフト管理
    path('manager/shifts/', views.ShiftManagementView.as_view(), name='shift_management'),
    path('manager/shifts/stats/', views.ShiftStatsView.as_view(), name='shift_stats'),
    path('manager/shifts/generate/', views.AutoGenerateShiftView.as_view(), name='shift_generate'),
    path('manager/shifts/update/', views.UpdateShiftStaffView.as_view(), name='shift_update'),
    path('manager/shifts/toggle-unavailable/', views.AdminToggleUnavailableDateView.as_view(), name='admin_toggle_unavailable'),
    path('manager/shifts/update-staff-shift/', views.AdminUpdateShiftView.as_view(), name='admin_update_staff_shift'),
    path('manager/shifts/clear/', views.ClearMonthlyShiftsView.as_view(), name='clear_monthly_shifts'),
    path('manager/shifts/<int:shift_id>/reassign/', views.ReassignShiftView.as_view(), name='shift_reassign'),
    path('manager/absences/<int:request_id>/approve/', views.AbsenceRequestApprovalView.as_view(), name='absence_approve'),

    # スタッフ用
    path('staff/dashboard/', views.StaffDashboardView.as_view(), name='staff_dashboard'),
    path('staff/unavailable/toggle/', views.ToggleUnavailableDateView.as_view(), name='unavailable_toggle'),
    path('staff/absence/request/', views.SubmitAbsenceRequestView.as_view(), name='absence_request'),
    path('staff/availability/submit/', views.SubmitAvailabilityView.as_view(), name='availability_submit'),
]
