from django.db import models
from django.contrib.auth.models import User

class Task(models.Model):
    """業務内容情報"""
    name = models.CharField(max_length=100, unique=True, verbose_name="業務名")
    required_people_per_day = models.PositiveIntegerField(default=1, verbose_name="1日あたりの必要人数")
    required_skill = models.CharField(max_length=200, blank=True, verbose_name="必要スキル")
    memo = models.TextField(blank=True, verbose_name="備考")

    class Meta:
        verbose_name = "業務"
        verbose_name_plural = "業務一覧"

    def __str__(self):
        return self.name

class Staff(models.Model):
    """パートスタッフ情報"""
    ROLE_CHOICES = [
        ('admin', '管理者'),
        ('staff', 'パートスタッフ'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='staff_profile', verbose_name="ユーザー")
    name = models.CharField(max_length=100, verbose_name="スタッフ名")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='staff', verbose_name="権限区分")
    available_tasks = models.ManyToManyField(Task, related_name='capable_staff', blank=True, verbose_name="担当可能業務")
    memo = models.TextField(blank=True, verbose_name="備考")

    class Meta:
        verbose_name = "スタッフ"
        verbose_name_plural = "スタッフ一覧"

    def __str__(self):
        return self.name

class UnavailableDate(models.Model):
    """勤務不可日情報"""
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='unavailable_dates', verbose_name="スタッフ")
    date = models.DateField(verbose_name="勤務不可日")

    class Meta:
        verbose_name = "勤務不可日"
        verbose_name_plural = "勤務不可日一覧"
        unique_together = ('staff', 'date')
        ordering = ['date']

    def __str__(self):
        return f"{self.staff.name} - {self.date}"

class Shift(models.Model):
    """シフト情報"""
    STATUS_CHOICES = [
        ('draft', '下書き'),
        ('confirmed', '確定'),
    ]

    date = models.DateField(verbose_name="日付")
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='shifts', verbose_name="業務")
    staff = models.ForeignKey(Staff, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_shifts', verbose_name="担当スタッフ")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft', verbose_name="ステータス")
    memo = models.TextField(blank=True, verbose_name="備考")

    class Meta:
        verbose_name = "シフト"
        verbose_name_plural = "シフト一覧"
        ordering = ['date', 'task']

    def __str__(self):
        staff_name = self.staff.name if self.staff else "未割り当て"
        return f"{self.date} - {self.task.name} - {staff_name}"

class AbsenceRequest(models.Model):
    """急な休み申請"""
    STATUS_CHOICES = [
        ('pending', '申請中'),
        ('approved', '承認'),
        ('rejected', '却下'),
    ]

    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name='absence_requests', verbose_name="スタッフ")
    date = models.DateField(verbose_name="日付")
    reason = models.TextField(blank=True, verbose_name="理由")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="ステータス")

    class Meta:
        verbose_name = "休み申請"
        verbose_name_plural = "休み申請一覧"
        unique_together = ('staff', 'date')
        ordering = ['-date']

    def __str__(self):
        return f"{self.staff.name} - {self.date} ({self.get_status_display()})"
