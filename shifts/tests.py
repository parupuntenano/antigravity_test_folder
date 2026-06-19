from datetime import date, timedelta
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse

from .models import Task, Staff, UnavailableDate, Shift, AbsenceRequest, AvailabilitySubmission
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

    def test_weekly_work_limit(self):
        """1週間に最大5日までしか同じスタッフにシフトが割り当てられないことを確認 (週休2日)"""
        target_year = 2026
        target_month = 6
        
        # スタッフA(受付のみ可能)を6/1〜6/7の全期間勤務不可にする
        for day in range(1, 8):
            UnavailableDate.objects.create(staff=self.staff1, date=date(2026, 6, day))
            
        # 6/1(月)〜6/7(日)まで毎日、受付の必要人数を1人にする
        # この期間にスタッフBが何日割り当てられるか確認する。
        # 担当可能なのはスタッフBのみだが、最大5日の制限により、2日は未割り当てになるはず
        success = generate_monthly_shifts(target_year, target_month)
        self.assertTrue(success)
        
        # 6/1〜6/7の間のスタッフBの割り当て数をカウント
        assigned_count = Shift.objects.filter(
            date__range=(date(2026, 6, 1), date(2026, 6, 7)),
            staff=self.staff2
        ).count()
        
        # 最大でも5日以下であることを検証
        self.assertLessEqual(assigned_count, 5)

    def test_weekly_unavailable_date_limit(self):
        """週に設定できる勤務不可日の上限が2日であることを検証"""
        # スタッフBでログイン
        self.client.login(username="staff2", password="password123")
        
        # 6/1(月)と6/2(火)を不可にする（同じ週）
        self.client.post(reverse('shifts:unavailable_toggle'), {'date': '2026-06-01'})
        self.client.post(reverse('shifts:unavailable_toggle'), {'date': '2026-06-02'})
        
        # 不可日が2日登録されていることを確認
        self.assertEqual(UnavailableDate.objects.filter(staff=self.staff2).count(), 2)
        
        # 3日目の6/3(水)を不可にしようとすると登録されないことを確認
        self.client.post(reverse('shifts:unavailable_toggle'), {'date': '2026-06-03'})
        self.assertEqual(UnavailableDate.objects.filter(staff=self.staff2).count(), 2)
        
        # 同一週ではない6/8(月)は不可に登録できることを検証
        self.client.post(reverse('shifts:unavailable_toggle'), {'date': '2026-06-08'})
        self.assertEqual(UnavailableDate.objects.filter(staff=self.staff2, date=date(2026, 6, 8)).count(), 1)
        self.assertEqual(UnavailableDate.objects.filter(staff=self.staff2).count(), 3)

    def test_availability_submission_and_lock(self):
        """希望提出と、提出後の変更制限・週2日設定による自動作成許可のテスト"""
        weeks_unavailable_days = [
            (date(2026, 6, 1), date(2026, 6, 2)),
            (date(2026, 6, 8), date(2026, 6, 9)),
            (date(2026, 6, 15), date(2026, 6, 16)),
            (date(2026, 6, 22), date(2026, 6, 23)),
            (date(2026, 6, 29), date(2026, 6, 30)),
        ]

        # 1. 登録がない状態で希望提出しようとするとエラーになることを確認（スタッフ側の提出制限は変更なし）
        self.client.login(username="staff2", password="password123")
        response = self.client.post(reverse('shifts:availability_submit'), {'year': 2026, 'month': 6}, follow=True)
        self.assertContains(response, "日しか設定されていません")

        # staff2の勤務不可日を各週2日ずつ設定
        for d1, d2 in weeks_unavailable_days:
            UnavailableDate.objects.create(staff=self.staff2, date=d1)
            UnavailableDate.objects.create(staff=self.staff2, date=d2)

        # 今度は提出できることを確認
        response = self.client.post(reverse('shifts:availability_submit'), {'year': 2026, 'month': 6}, follow=True)
        self.assertContains(response, "希望を提出しました")
        self.assertTrue(AvailabilitySubmission.objects.filter(staff=self.staff2, year=2026, month=6).exists())

        # 2. 提出後に勤務不可日を変更（トグル）しようとするとエラーになることを確認
        response = self.client.post(reverse('shifts:unavailable_toggle'), {'date': '2026-06-01'}, follow=True)
        self.assertContains(response, "変更できません")
        # 削除されていないことを検証
        self.assertTrue(UnavailableDate.objects.filter(staff=self.staff2, date=date(2026, 6, 1)).exists())

        # 3. staff1がまだ週2日設定をしていないので、管理者が自動作成しようとするとエラーになることを確認
        self.client.login(username="admin_user", password="password123")
        response = self.client.post(reverse('shifts:shift_generate'), {'year': 2026, 'month': 6}, follow=True)
        self.assertContains(response, "週2日の休日希望が未設定のスタッフがいるため")

        # staff1の分も週に2日設定する（提出はしなくてよい）
        for d1, d2 in weeks_unavailable_days:
            UnavailableDate.objects.create(staff=self.staff1, date=d1)
            UnavailableDate.objects.create(staff=self.staff1, date=d2)

        # 全員が週2日設定済みなので、提出なしでも自動作成が成功することを確認
        response = self.client.post(reverse('shifts:shift_generate'), {'year': 2026, 'month': 6}, follow=True)
        self.assertContains(response, "シフトを自動作成しました")

    def test_admin_toggle_unavailable(self):
        """管理者がスタッフの勤務不可日をトグルできるか検証"""
        self.client.login(username="admin_user", password="password123")
        
        # 初期状態では不可日が存在しないことを確認
        self.assertFalse(UnavailableDate.objects.filter(staff=self.staff1, date=date(2026, 6, 1)).exists())
        
        # 勤務不可に設定するPOST
        response = self.client.post(
            reverse('shifts:admin_toggle_unavailable'),
            {'staff_id': self.staff1.id, 'date': '2026-06-01'},
            follow=True
        )
        self.assertContains(response, "勤務不可に設定しました")
        self.assertTrue(UnavailableDate.objects.filter(staff=self.staff1, date=date(2026, 6, 1)).exists())
        
        # もう一度POSTして解除されることを確認
        response = self.client.post(
            reverse('shifts:admin_toggle_unavailable'),
            {'staff_id': self.staff1.id, 'date': '2026-06-01'},
            follow=True
        )
        self.assertContains(response, "勤務可能に設定しました")
        self.assertFalse(UnavailableDate.objects.filter(staff=self.staff1, date=date(2026, 6, 1)).exists())

    def test_admin_update_staff_shift(self):
        """管理者がスタッフの業務割り当てを直接変更できるか検証"""
        self.client.login(username="admin_user", password="password123")
        
        # 1. 新規割り当てのテスト
        response = self.client.post(
            reverse('shifts:admin_update_staff_shift'),
            {'staff_id': self.staff1.id, 'date': '2026-06-01', 'task_id': self.task_a.id},
            follow=True
        )
        self.assertContains(response, "割り当てました")
        self.assertTrue(Shift.objects.filter(staff=self.staff1, date=date(2026, 6, 1), task=self.task_a).exists())
        
        # 2. 割り当て解除 (task_id='') のテスト
        response = self.client.post(
            reverse('shifts:admin_update_staff_shift'),
            {'staff_id': self.staff1.id, 'date': '2026-06-01', 'task_id': ''},
            follow=True
        )
        self.assertContains(response, "割り当てを解除しました")
        # 該当日にスタッフAが入っているシフトはないはず
        self.assertFalse(Shift.objects.filter(staff=self.staff1, date=date(2026, 6, 1)).exists())

    def test_clear_monthly_shifts(self):
        """管理者がシフトをクリアして休日調整に戻せるか検証"""
        self.client.login(username="admin_user", password="password123")
        
        # シフトを作成しておく
        Shift.objects.create(date=date(2026, 6, 1), task=self.task_a, staff=self.staff1)
        self.assertTrue(Shift.objects.filter(date__year=2026, date__month=6).exists())
        
        # クリアを実行
        response = self.client.post(
            reverse('shifts:clear_monthly_shifts'),
            {'year': 2026, 'month': 6},
            follow=True
        )
        self.assertContains(response, "第一段階（休日調整）に戻しました")
        self.assertFalse(Shift.objects.filter(date__year=2026, date__month=6).exists())

    def test_batch_save_stage_1_holidays(self):
        """第一段階（休日調整）での休日希望の一括保存を検証"""
        self.client.login(username="admin_user", password="password123")
        
        # 初期状態で不可日が存在しないことを確認
        self.assertFalse(UnavailableDate.objects.filter(date__year=2026, date__month=6).exists())
        
        # 6/1にスタッフA、6/2にスタッフBの休日希望を一括保存
        response = self.client.post(
            reverse('shifts:shift_management') + "?year=2026&month=6",
            {
                'stage': 'stage_1',
                'unavailable_dates': [
                    f"{self.staff1.id}_2026-06-01",
                    f"{self.staff2.id}_2026-06-02"
                ]
            },
            follow=True
        )
        self.assertContains(response, "休日希望（勤務不可日）を一括保存しました")
        self.assertTrue(UnavailableDate.objects.filter(staff=self.staff1, date=date(2026, 6, 1)).exists())
        self.assertTrue(UnavailableDate.objects.filter(staff=self.staff2, date=date(2026, 6, 2)).exists())
        self.assertEqual(UnavailableDate.objects.filter(date__year=2026, date__month=6).count(), 2)

        # 二回目の保存で、スタッフBの休日希望を外し、スタッフAのみ残す
        response = self.client.post(
            reverse('shifts:shift_management') + "?year=2026&month=6",
            {
                'stage': 'stage_1',
                'unavailable_dates': [
                    f"{self.staff1.id}_2026-06-01"
                ]
            },
            follow=True
        )
        self.assertContains(response, "休日希望（勤務不可日）を一括保存しました")
        self.assertTrue(UnavailableDate.objects.filter(staff=self.staff1, date=date(2026, 6, 1)).exists())
        self.assertFalse(UnavailableDate.objects.filter(staff=self.staff2, date=date(2026, 6, 2)).exists())
        self.assertEqual(UnavailableDate.objects.filter(date__year=2026, date__month=6).count(), 1)

    def test_batch_save_stage_2_assignments(self):
        """第二段階（業務割り当て）での業務割り当ての一括保存を検証"""
        self.client.login(username="admin_user", password="password123")
        
        # 事前に空のスロット（未割り当てシフト）を作成しておく
        shift_a = Shift.objects.create(date=date(2026, 6, 1), task=self.task_a, staff=None)
        shift_b = Shift.objects.create(date=date(2026, 6, 1), task=self.task_b, staff=None)
        
        # スタッフAに受付(task_a)、スタッフBにレジ(task_b)を一括で割り当てる
        response = self.client.post(
            reverse('shifts:shift_management') + "?year=2026&month=6",
            {
                'stage': 'stage_2',
                f'task_{self.staff1.id}_2026-06-01': self.task_a.id,
                f'task_{self.staff2.id}_2026-06-01': self.task_b.id,
            },
            follow=True
        )
        self.assertContains(response, "シフト業務割り当てを一括保存しました")
        
        # 割り当て状況の検証
        shift_a.refresh_from_db()
        shift_b.refresh_from_db()
        self.assertEqual(shift_a.staff, self.staff1)
        self.assertEqual(shift_b.staff, self.staff2)
        
        # 一部の割り当てを変更・解除する
        # スタッフAを解除 (空文字)、スタッフBをレジ(task_b)から受付(task_a)に変更
        response = self.client.post(
            reverse('shifts:shift_management') + "?year=2026&month=6",
            {
                'stage': 'stage_2',
                f'task_{self.staff1.id}_2026-06-01': '',
                f'task_{self.staff2.id}_2026-06-01': self.task_a.id,
            },
            follow=True
        )
        self.assertContains(response, "シフト業務割り当てを一括保存しました")
        
        # スタッフAの割り当てが解除されていること
        self.assertFalse(Shift.objects.filter(date=date(2026, 6, 1), staff=self.staff1).exists())
        
        # スタッフBが受付(task_a)になっていること
        shift_a.refresh_from_db()
        self.assertEqual(shift_a.staff, self.staff2)

