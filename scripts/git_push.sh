#!/bin/bash
# Push to GitHub as backup
cd /home/oracle/oracle-lab
mkdir -p logs
git push origin main >> logs/git_push.log 2>&1
