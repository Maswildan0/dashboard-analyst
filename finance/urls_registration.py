from django.urls import path

from . import registration_views

app_name = 'registration'

urlpatterns = [
    path('', registration_views.registrasi_mahasiswa, name='index'),
    path('data/', registration_views.registrasi_mahasiswa_data, name='data'),
    path('program-studi/', registration_views.registrasi_mahasiswa_programs, name='programs'),
    path('template/', registration_views.student_intake_template, name='template'),
    path('upload/preview/', registration_views.student_intake_preview, name='upload-preview'),
    path('upload/confirm/', registration_views.student_intake_confirm, name='upload-confirm'),
]
