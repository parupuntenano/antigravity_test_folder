from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from .models import Staff, Task, AbsenceRequest

class StaffForm(forms.ModelForm):
    login_id = forms.CharField(
        max_length=150,
        label="ログインID",
        help_text="ログインに使用する一意のIDを入力してください。"
    )
    password = forms.CharField(
        widget=forms.PasswordInput(render_value=False),
        label="パスワード",
        required=False,
        help_text="新規登録時は必須です。変更しない場合は空欄にしてください。"
    )

    class Meta:
        model = Staff
        fields = ['name', 'role', 'available_tasks', 'memo']
        widgets = {
            'available_tasks': forms.CheckboxSelectMultiple(),
            'memo': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 編集時の初期値を設定
        if self.instance and self.instance.pk:
            self.fields['login_id'].initial = self.instance.user.username
            self.fields['password'].required = False
        else:
            self.fields['password'].required = True

    def clean_login_id(self):
        login_id = self.cleaned_data.get('login_id')
        # 重複チェック（自分自身を除く）
        qs = User.objects.filter(username=login_id)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.user.pk)
        if qs.exists():
            raise ValidationError("このログインIDはすでに使用されています。")
        return login_id

    def save(self, commit=True):
        login_id = self.cleaned_data.get('login_id')
        password = self.cleaned_data.get('password')
        
        if self.instance and self.instance.pk:
            # 既存のユーザー情報を更新
            user = self.instance.user
            user.username = login_id
            if password:
                user.set_password(password)
            user.save()
            staff = super().save(commit=False)
        else:
            # 新規のユーザーとスタッフを作成
            user = User.objects.create_user(username=login_id, password=password)
            staff = super().save(commit=False)
            staff.user = user

        if commit:
            staff.save()
            self.save_m2m() # ManyToMany (available_tasks) を保存するために必要
        return staff

class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['name', 'required_people_per_day', 'required_skill', 'memo']
        widgets = {
            'memo': forms.Textarea(attrs={'rows': 3}),
        }

class AbsenceRequestForm(forms.ModelForm):
    class Meta:
        model = AbsenceRequest
        fields = ['date', 'reason']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'reason': forms.Textarea(attrs={'rows': 3, 'placeholder': '休む理由を入力してください。'}),
        }
