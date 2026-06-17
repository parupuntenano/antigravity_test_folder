from datetime import date, timedelta
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse

from .models import Task, Staff, UnavailableDate, Shift, AbsenceRequest
from .scheduler import generate_monthly_shifts, get_month_warnings

class ShiftSystemTests(TestCase):
    
    def setUp(self):
        # 1. 業務（タスク）の作成
        self.task_a = Task.objects.create(name="受付", required_people_per_day=1)
        self.task_b = Task.objects.create(name="レジ", required_people_per_day=1)
        
        # 2. スタッフアカウントの作成
        # 管理者
        self.admin_user = User.objects.create_user(username="admin_user", password="password123")
        self.admin_staff = Staff.objects.create(
            user=self.admin_user,
            name="管理者A",
            role="admin"
        )
        
        # パートスタッフ1 (受付のみ可能)
        self.staff_user1 = User.objects.create_user(username="staff1", password="password123")
        self.staff1 = Staff.objects.create(
            user=self.staff_user1,
            name="スタッフA",
            role="staff"
        )
        self.staff1.available_tasks.add(self.task_a)
        
        # パートスタッフ2 (受付、レジ両方可能)
        self.staff_user2 = User.objects.create_user(username="staff2", password="password123")
        self.staff2 = Staff.objects.create(
            user=self.staff_user2,
            name="スタッフB",
            role="staff"
        )
        self.staff2.available_tasks.add(self.task_a, self.task_b)

    def test_permission_restrictions(self):
        """管理者用画面に一般スタッフがアクセスできないことを確認"""
        self.client.login(username="staff1", password="password123")
        response = self.client.get(reverse('shifts:admin_dashboard'))
        self.assertEqual(response.status_code, 403)
        
        # 管理者でログインし直す
        self.client.login(username="admin_user", password="password123")
        response = self.client.get(reverse('shifts:admin_dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_auto_scheduling_availability(self):
        """勤務不可日のスタッフがスケジュールから除外されるかテスト"""
        target_year = 2026
        target_month = 6
        
        # スタッフBは6/1を勤務不可に設定
        UnavailableDate.objects.create(staff=self.staff2, date=date(2026, 6, 1))
        
        # シフトの自動生成を実行
        success = generate_monthly_shifts(target_year, target_month)
        self.assertTrue(success)
        
        # 6/1の「レジ」シフトを確認
        # スタッフBが勤務不可なので、レジは割り当て可能な人がおらず未割り当て(None)になるはず
        shift_regi = Shift.objects.filter(date=date(2026, 6, 1), task=self.task_b).first()
        self.assertIsNotNone(shift_regi)
        self.assertIsNone(shift_regi.staff)
        
        # 一方、6/1の「受付」はスタッフA（勤務可能）が入っているはず
        shift_uketsuke = Shift.objects.filter(date=date(2026, 6, 1), task=self.task_a).first()
        self.assertIsNotNone(shift_uketsuke)
        self.assertEqual(shift_uketsuke.staff, self.staff1)

    def test_consecutive_duty_warning(self):
        """同じ業務が連続した場合に警告が正しく検出されるかテスト"""
        # 手動で6/1と6/2にスタッフAを受付に配置
        shift1 = Shift.objects.create(date=date(2026, 6, 1), task=self.task_a, staff=self.staff1)
        shift2 = Shift.objects.create(date=date(2026, 6, 2), task=self.task_a, staff=self.staff1)
        
        # 警告情報を取得
        warnings = get_month_warnings(2026, 6)
        
        # 6/2のシフトに対して連続勤務の警告が出ているか検証
        self.assertIn(shift2.id, warnings)
        self.assertTrue(any("連続しています" in w for w in warnings[shift2.id]))

    def test_absence_request_shift_release(self):
        """急な休み申請が承認された際、自動でシフト担当が解除されることを確認"""
        # シフトを作成
        shift = Shift.objects.create(date=date(2026, 6, 10), task=self.task_a, staff=self.staff1)
        
        # 休み申請を作成
        abs_req = AbsenceRequest.objects.create(
            staff=self.staff1,
            date=date(2026, 6, 10),
            reason="急病のため",
            status='pending'
        )
        
        # 申請を承認するPOSTをシミュレート
        self.client.login(username="admin_user", password="password123")
        response = self.client.post(
            reverse('shifts:absence_approve', kwargs={'request_id': abs_req.id}),
            {'action': 'approve'}
        )
        
        # シフトの担当が解除(None)されていることを検証
        shift.refresh_from_db()
        self.assertIsNone(shift.staff)
        
        # 申請ステータスが'approved'になっていることを検証
        abs_req.refresh_from_db()
        self.assertEqual(abs_req.status, 'approved')
