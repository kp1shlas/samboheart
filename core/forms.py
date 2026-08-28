from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm


class RegistrationForm(UserCreationForm):
    """Форма регистрации родителя"""

    first_name = forms.CharField(
        label='Имя',
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2.5 border border-gray-300 '
                     'rounded-xl focus:ring-2 focus:ring-red-500 '
                     'focus:border-red-500 outline-none transition',
            'placeholder': 'Иван',
        })
    )

    last_name = forms.CharField(
        label='Фамилия',
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2.5 border border-gray-300 '
                     'rounded-xl focus:ring-2 focus:ring-red-500 '
                     'focus:border-red-500 outline-none transition',
            'placeholder': 'Иванов',
        })
    )

    email = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs={
            'class': 'w-full px-4 py-2.5 border border-gray-300 '
                     'rounded-xl focus:ring-2 focus:ring-red-500 '
                     'focus:border-red-500 outline-none transition',
            'placeholder': 'ivanov@example.com',
        })
    )

    phone = forms.CharField(
        label='Телефон',
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2.5 border border-gray-300 '
                     'rounded-xl focus:ring-2 focus:ring-red-500 '
                     'focus:border-red-500 outline-none transition',
            'placeholder': '+7 (900) 123-45-67',
        })
    )

    username = forms.CharField(
        label='Логин',
        max_length=50,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2.5 border border-gray-300 '
                     'rounded-xl focus:ring-2 focus:ring-red-500 '
                     'focus:border-red-500 outline-none transition',
            'placeholder': 'ivanov_i',
        })
    )

    password1 = forms.CharField(
        label='Пароль',
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-4 py-2.5 border border-gray-300 '
                     'rounded-xl focus:ring-2 focus:ring-red-500 '
                     'focus:border-red-500 outline-none transition',
            'placeholder': 'Минимум 8 символов',
        })
    )

    password2 = forms.CharField(
        label='Повторите пароль',
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-4 py-2.5 border border-gray-300 '
                     'rounded-xl focus:ring-2 focus:ring-red-500 '
                     'focus:border-red-500 outline-none transition',
            'placeholder': 'Повторите пароль',
        })
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'username',
                  'password1', 'password2']
        