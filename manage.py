#!/usr/bin/env python
"""
[홍석환] Django 관리 명령 실행 진입점
프로젝트 설정을 지정하고 Django의 관리 명령을 실행한다.
"""
import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
from django.core.management import execute_from_command_line
execute_from_command_line(sys.argv)
