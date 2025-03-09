# Generated by Django 5.1.4 on 2025-03-08 02:26

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('recommender', '0002_teacherprofile_delete_studentguide_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='RecommendationOverride',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('old_recommendation', models.IntegerField(choices=[(0, 'Arts'), (1, 'Business'), (2, 'Healthcare'), (3, 'Humanities'), (4, 'STEM')])),
                ('new_recommendation', models.IntegerField(choices=[(0, 'Arts'), (1, 'Business'), (2, 'Healthcare'), (3, 'Humanities'), (4, 'STEM')])),
                ('reason', models.TextField(blank=True, help_text='Reason for override', null=True)),
                ('timestamp', models.DateTimeField(auto_now_add=True)),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='recommender.studentprofile')),
                ('teacher', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='recommender.teacherprofile')),
            ],
        ),
    ]
