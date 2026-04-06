# biliterminal

这个仓库当前承载的是一个 Bilibili CLI/TUI 项目，代码集中在 [bili_terminal](./bili_terminal)。

## 快速启动

```bash
chmod +x bili_terminal/start.sh
./bili_terminal/start.sh
```

也可以直接：

```bash
python3 -m bili_terminal tui
```

## 常用命令

```bash
./bili_terminal/start.sh recommend -n 5
./bili_terminal/start.sh search 中文 -n 5
./bili_terminal/start.sh comments BV19K9uBmEdx -n 3
```

## 测试

```bash
python3 -m unittest discover -s bili_terminal/tests -v
```
