# Bilibili CLI

把 Bilibili 常用网页浏览动作搬到终端里。

## 快速启动

最短路径：

```bash
cd bili_terminal
chmod +x start.sh
./start.sh
```

不想进目录也可以：

```bash
python3 -m bili_terminal tui
```

如果想直接启动某个命令：

```bash
chmod +x bili_terminal/start.sh
./bili_terminal/start.sh recommend -n 5
./bili_terminal/start.sh search 中文 -n 5
./bili_terminal/start.sh comments BV19K9uBmEdx -n 3
```

## 测试

```bash
python3 -m unittest discover -s bili_terminal/tests -v
```
