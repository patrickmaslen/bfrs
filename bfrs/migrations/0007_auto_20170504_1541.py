# -*- coding: utf-8 -*-
# Generated by Django 1.10.2 on 2017-05-04 07:41
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bfrs', '0006_auto_20170504_1520'),
    ]

    operations = [
        migrations.AlterField(
            model_name='snapshothistory',
            name='action',
            field=models.CharField(max_length=36, verbose_name=b'Action Type'),
        ),
    ]