#!/bin/bash
# Push to GitHub as backup
cd /root/oracle-lab
mkdir -p logs
git push origin main >> logs/git_push.log 2>&1
