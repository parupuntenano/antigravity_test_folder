import random
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from shifts.models import Task, Staff, UnavailableDate, Shift

class Command(BaseCommand):
    help = 'データベースにテスト用のサンプルデータを登録します（管理者1名、業務4種、スタッフ50名）'

    def handle(self, *args, **options):
        self.stdout.write('サンプルデータの作成を開始します...')

        # 1. 既存データのクリア
        Shift.objects.all().delete()
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

        # 3. 業務（タスク）の作成（30種類、1日の必要人数合計：35名）
        tasks_data = [
            {'name': '受付', 'required_people_per_day': 2, 'required_skill': '接客スキル', 'memo': 'フロントでの来客対応・電話応対'},
            {'name': 'レジ', 'required_people_per_day': 2, 'required_skill': 'レジ研修修了', 'memo': '会計・精算業務'},
            {'name': '案内', 'required_people_per_day': 1, 'required_skill': '', 'memo': 'フロア巡回・顧客への場所案内'},
            {'name': '清掃', 'required_people_per_day': 1, 'required_skill': '', 'memo': '館内の巡回清掃・衛生管理'},
            {'name': '品出し', 'required_people_per_day': 2, 'required_skill': '', 'memo': '商品の棚出し・陳列作業'},
            {'name': '検品', 'required_people_per_day': 1, 'required_skill': '', 'memo': '入荷商品の数量・破損チェック'},
            {'name': 'ピッキング', 'required_people_per_day': 2, 'required_skill': '', 'memo': '注文票に基づいた商品の集荷'},
            {'name': '梱包', 'required_people_per_day': 2, 'required_skill': '', 'memo': '商品の箱詰め・発送準備'},
            {'name': '在庫管理', 'required_people_per_day': 1, 'required_skill': '', 'memo': '在庫の計上・データ確認'},
            {'name': '事務', 'required_people_per_day': 1, 'required_skill': '', 'memo': '伝票処理・PCデータ入力'},
            {'name': '電話応対', 'required_people_per_day': 1, 'required_skill': '', 'memo': '問い合わせ対応・内線取り次ぎ'},
            {'name': 'フロント', 'required_people_per_day': 1, 'required_skill': '', 'memo': '来訪者の受付・案内'},
            {'name': '発注', 'required_people_per_day': 1, 'required_skill': '', 'memo': '備品や商品の発注業務'},
            {'name': '調理', 'required_people_per_day': 2, 'required_skill': '調理師または経験者', 'memo': 'キッチンでの調理業務'},
            {'name': 'ドリンク', 'required_people_per_day': 1, 'required_skill': '', 'memo': 'ドリンクの作成・提供'},
            {'name': '洗い場', 'required_people_per_day': 1, 'required_skill': '', 'memo': '食器・調理器具の洗浄'},
            {'name': '配達', 'required_people_per_day': 1, 'required_skill': '要普通免許', 'memo': '近隣への商品お届け'},
            {'name': 'ホール', 'required_people_per_day': 1, 'required_skill': '', 'memo': '客席の片付け・オーダーテイク'},
            {'name': '会計', 'required_people_per_day': 1, 'required_skill': '', 'memo': 'レジの集計・売上金の管理'},
            {'name': '見回り', 'required_people_per_day': 1, 'required_skill': '', 'memo': '安全確認のための施設内巡回'},
            {'name': '発送', 'required_people_per_day': 1, 'required_skill': '', 'memo': '発送商品の仕分け・出荷対応'},
            {'name': '仕分け', 'required_people_per_day': 1, 'required_skill': '', 'memo': '商品のカテゴリ別仕分け・棚卸し'},
            {'name': 'レジ応援', 'required_people_per_day': 1, 'required_skill': 'レジ研修修了', 'memo': '混雑時のレジサポート'},
            {'name': 'サポート', 'required_people_per_day': 1, 'required_skill': '', 'memo': '各部門のヘルプ・アシスタント業務'},
            {'name': '開店準備', 'required_people_per_day': 1, 'required_skill': '', 'memo': '朝の鍵開け・レジ金準備・清掃'},
            {'name': '閉店作業', 'required_people_per_day': 1, 'required_skill': '', 'memo': '夕方の施錠・レジ締め・清掃'},
            {'name': 'トラブル対応', 'required_people_per_day': 1, 'required_skill': '経験者優遇', 'memo': '機器の不具合や顧客トラブル対応の補助'},
            {'name': 'システム点検', 'required_people_per_day': 1, 'required_skill': '', 'memo': '通信機器やPOSレジの点検・確認'},
            {'name': 'カウンター', 'required_people_per_day': 1, 'required_skill': '接客スキル', 'memo': 'インフォメーションカウンターでの応対'},
            {'name': '荷受け', 'required_people_per_day': 1, 'required_skill': '', 'memo': 'トラックからの荷下ろし・伝票確認'},
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
            
            # ランダムで6〜12個のタスクを担当可能に設定
            num_tasks = random.randint(6, 12)
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
