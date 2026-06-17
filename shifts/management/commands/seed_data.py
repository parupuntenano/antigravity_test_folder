import random
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from shifts.models import Task, Staff, UnavailableDate

class Command(BaseCommand):
    help = 'データベースにテスト用のサンプルデータを登録します（管理者1名、業務4種、スタッフ50名）'

    def handle(self, *args, **options):
        self.stdout.write('サンプルデータの作成を開始します...')

        # 1. 既存データのクリア
        User.objects.exclude(is_superuser=True).delete()
        Task.objects.all().delete()

        # 2. 管理者ユーザーの作成
        admin_user, created = User.objects.get_or_create(username='admin')
        admin_user.set_password('password')
        admin_user.save()
        
        admin_staff, _ = Staff.objects.get_or_create(
            user=admin_user,
            defaults={
                'name': '管理者',
                'role': 'admin',
                'memo': 'シフト管理責任者'
            }
        )
        self.stdout.write('管理者アカウントを作成しました: ID=admin / Password=password')

        # 3. 業務（タスク）の作成
        tasks_data = [
            {'name': '受付', 'required_people_per_day': 2, 'required_skill': '接客スキル', 'memo': 'フロントでの来客対応・電話応対'},
            {'name': 'レジ', 'required_people_per_day': 3, 'required_skill': 'レジ研修修了', 'memo': '会計・精算業務'},
            {'name': '案内', 'required_people_per_day': 2, 'required_skill': '', 'memo': 'フロア巡回・顧客への場所案内'},
            {'name': '清掃', 'required_people_per_day': 1, 'required_skill': '', 'memo': '館内の巡回清掃・衛生管理'},
        ]
        
        tasks = []
        for t_info in tasks_data:
            task = Task.objects.create(**t_info)
            tasks.append(task)
            self.stdout.write(f"業務「{task.name}」を作成しました (必要人数: {task.required_people_per_day}名)")

        # 4. パートスタッフ50名の作成
        first_names = ['太郎', '次郎', '花子', '梅子', '健太', '美咲', '大輔', 'さくら', '拓也', '翔太', '結衣', '陽菜', '蓮', '湊', '大和', '葵', '真央', '洋子', '浩一', '純']
        last_names = ['佐藤', '鈴木', '高橋', '田中', '渡辺', '伊藤', '中村', '小林', '加藤', '吉田', '山田', '佐々木', '山口', '松本', '井上', '木村', '林', '斎藤', '清水', '山崎']

        today = date.today()
        # 勤務不可日のランダム作成用 (今月の日付)
        start_date = date(today.year, today.month, 1)
        
        for i in range(1, 51):
            username = f"staff{i}"
            password = "password"
            
            # ランダムなフルネームを生成
            name = f"{random.choice(last_names)} {random.choice(first_names)}"
            
            user = User.objects.create_user(username=username, password=password)
            staff = Staff.objects.create(
                user=user,
                name=name,
                role='staff',
                memo=f"パートスタッフNo.{i:02d}"
            )
            
            # ランダムで1〜3個のタスクを担当可能に設定
            num_tasks = random.randint(1, 3)
            assigned_tasks = random.sample(tasks, num_tasks)
            staff.available_tasks.add(*assigned_tasks)
            
            # ランダムに2〜4日間の勤務不可日を設定
            num_unavail = random.randint(2, 4)
            unavail_days = random.sample(range(1, 29), num_unavail)
            for day_num in unavail_days:
                unavail_date = date(today.year, today.month, day_num)
                UnavailableDate.objects.create(staff=staff, date=unavail_date)

        self.stdout.write('スタッフ50名の作成が完了しました！ (ログインID: staff1〜staff50 / パパスワード: password)')
        self.stdout.write('サンプルデータの登録がすべて完了しました。')
