from django.urls import path

from . import registration_views

app_name = 'registration'

urlpatterns = [
    path('', registration_views.registrasi_mahasiswa, name='index'),
    path('data/', registration_views.registrasi_mahasiswa_data, name='data'),
    path('program-studi/', registration_views.registrasi_mahasiswa_programs, name='programs'),
]
