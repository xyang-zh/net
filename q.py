#!/usr/bin/env python3

import subprocess
import re
import time
import argparse
from typing import Dict, Tuple, Set

def get_queue_stats(netns: str, iface: str, mode: str):
    if netns:
        cmd = f"ip netns exec {netns} ethtool -S {iface}"
    else:
        cmd = f"ethtool -S {iface}"
    try:
        result = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, text=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"执行失败: {e.output}") from e

    if mode == "mlx":
        rx_pkt_pattern = re.compile(r"rx(\d+)_packets: (\d+)")
        rx_byte_pattern = re.compile(r"rx(\d+)_bytes: (\d+)")
        tx_pkt_pattern = re.compile(r"tx(\d+)_packets: (\d+)")
        tx_byte_pattern = re.compile(r"tx(\d+)_bytes: (\d+)")
    elif mode == "virtio":
        rx_pkt_pattern = re.compile(r"rx_queue_(\d+)_packets:\s+(\d+)")
        rx_byte_pattern = re.compile(r"rx_queue_(\d+)_bytes:\s+(\d+)")
        tx_pkt_pattern = re.compile(r"tx_queue_(\d+)_packets:\s+(\d+)")
        tx_byte_pattern = re.compile(r"tx_queue_(\d+)_bytes:\s+(\d+)")

    rx_pkt_stats = {int(queue): int(count) for queue, count in rx_pkt_pattern.findall(result)}
    rx_byte_stats = {int(queue): int(count) for queue, count in rx_byte_pattern.findall(result)}
    tx_pkt_stats = {int(queue): int(count) for queue, count in tx_pkt_pattern.findall(result)}
    tx_byte_stats = {int(queue): int(count) for queue, count in tx_byte_pattern.findall(result)}

    if not (rx_pkt_stats or tx_pkt_stats):
        raise ValueError("未找到队列统计")

    return rx_pkt_stats, rx_byte_stats, tx_pkt_stats, tx_byte_stats

def calculate_speed(prev_stats: Dict[int, int], curr_stats: Dict[int, int], interval: float, is_bytes: bool = False):
    speed_stats = {}
    all_queues = set(prev_stats.keys()) | set(curr_stats.keys())

    for queue in sorted(all_queues):
        prev_val = prev_stats.get(queue, 0)
        curr_val = curr_stats.get(queue, 0)
        diff = curr_val - prev_val

        if diff < 0:
            diff = curr_val + (2**32 - prev_val)

        if is_bytes:
            speed = diff / interval / (1024 * 1024)
        else:
            speed = diff / interval

        speed_stats[queue] = round(speed, 2)

    return speed_stats

def print_speed_table(rx_pps_stats, rx_mbps_stats, tx_pps_stats, tx_mbps_stats, title="队列统计"):
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RESET = '\033[0m'

    print(f"\n{title}")
    print("-" * 80)
    print(f"{'队列号':<6} {GREEN}{'接收 pps':<14}{RESET} {GREEN}{'接收速度 MB/s':<14}{RESET} {YELLOW}{'发送 pps':<15}{RESET} {YELLOW}{'发送速度 MB/s':<15}{RESET}")
    print("-" * 80)

    all_queues = set(rx_pps_stats.keys()) | set(tx_pps_stats.keys())

    for queue in sorted(all_queues):
        rx_pps = rx_pps_stats.get(queue, 0)
        rx_mbps = rx_mbps_stats.get(queue, 0)
        tx_pps = tx_pps_stats.get(queue, 0)
        tx_mbps = tx_mbps_stats.get(queue, 0)

        print(f"{queue:<10} {GREEN}{rx_pps:<15.2f}{RESET} {GREEN}{rx_mbps:<18.2f}{RESET} {YELLOW}{tx_pps:<18.2f}{RESET} {YELLOW}{tx_mbps:<15.2f}{RESET}")

    total_rx_pps = sum(rx_pps_stats.values())
    total_rx_mbps = sum(rx_mbps_stats.values())
    total_tx_pps = sum(tx_pps_stats.values())
    total_tx_mbps = sum(tx_mbps_stats.values())

    print("-" * 80)
    print(f"{'总计':<6} {GREEN}{total_rx_pps:<15.2f}{RESET} {GREEN}{total_rx_mbps:<18.2f}{RESET} {YELLOW}{total_tx_pps:<15.2f}{RESET} {YELLOW}{total_tx_mbps:<15.2f}{RESET}")

def main():
    parser = argparse.ArgumentParser(description="统计网卡队列速度")
    parser.add_argument("-n", "--netns", default="", help="网络命名空间（为空则使用主机命名空间）")
    parser.add_argument("-i", "--iface", required=True, help="网卡名称")
    parser.add_argument("-t", "--interval", type=float, default=1.0, help="统计间隔")
    parser.add_argument("-c", "--continuous", action="store_true", help="连续监控")
    parser.add_argument("-C", "--count", type=int, default=0, help="监控次数")
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("-m", "--mlx", action="store_const", const="mlx", dest="mode", help="mlx驱动模式")
    mode_group.add_argument("-v", "--virtio", action="store_const", const="virtio", dest="mode", help="virtio驱动模式")
    args = parser.parse_args()

    try:
        if args.netns:
            print(f"监控 {args.netns}/{args.iface}")
        else:
            print(f"监控 {args.iface}（主机命名空间）")
        print(f"间隔: {args.interval}秒")
        print(f"驱动模式: {args.mode}")

        if args.continuous:
            print("连续监控模式")
            if args.count > 0:
                print(f"监控次数: {args.count}")

        monitor_count = 0

        while True:
            prev_rx_pkt, prev_rx_byte, prev_tx_pkt, prev_tx_byte = get_queue_stats(args.netns, args.iface, args.mode)

            time.sleep(args.interval)

            curr_rx_pkt, curr_rx_byte, curr_tx_pkt, curr_tx_byte = get_queue_stats(args.netns, args.iface, args.mode)

            rx_pps_stats = calculate_speed(prev_rx_pkt, curr_rx_pkt, args.interval, False)
            rx_mbps_stats = calculate_speed(prev_rx_byte, curr_rx_byte, args.interval, True)
            tx_pps_stats = calculate_speed(prev_tx_pkt, curr_tx_pkt, args.interval, False)
            tx_mbps_stats = calculate_speed(prev_tx_byte, curr_tx_byte, args.interval, True)

            timestamp = time.strftime("%H:%M:%S")
            print_speed_table(rx_pps_stats, rx_mbps_stats, tx_pps_stats, tx_mbps_stats, f"时间: {timestamp}")

            monitor_count += 1
            if args.count > 0 and monitor_count >= args.count:
                break
            if not args.continuous:
                break

            print()

    except KeyboardInterrupt:
        print("\n监控已停止")
    except Exception as e:
        print(f"错误: {e}")
        exit(1)

if __name__ == "__main__":
    main()
