# telegram-output-monitor-bot
>  简单粗暴的telegram bot监控输出文件并发送给用户

使用时修改文件名`sample-cfg.ini`为`cfg.ini`，然后填入BOT信息和要监控的文件路径

安装必要的包（如果不用代理，不需要pysocks）

```
pip3 install python-telegram-bot
pip3 install pysocks
```

然后`crontab -e`添加一行：

```
* * * * * python3 <monitor.py的完整路径>
```

