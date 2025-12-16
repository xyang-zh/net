#!/usr/bin/env python3

import argparse
import subprocess
import sys
import re
import os
from typing import List, Optional, Dict, Tuple


class ColorPrinter:
    @staticmethod
    def red(text: str) -> None:
        print(f'\033[31m{text}\033[0m')

    @staticmethod
    def green(text: str) -> None:
        print(f'\033[32m{text}\033[0m')

    @staticmethod
    def yellow(text: str) -> None:
        print(f'\033[33m{text}\033[0m')

    @staticmethod
    def blue(text: str) -> None:
        print(f'\033[34m{text}\033[0m')

    @staticmethod
    def cyan(text: str) -> None:
        print(f'\033[36m{text}\033[0m')

    @staticmethod
    def bold(text: str) -> None:
        print(f'\033[1m{text}\033[0m')

    @staticmethod
    def bold_red(text: str) -> None:
        print(f'\033[1;31m{text}\033[0m')

    @staticmethod
    def bold_green(text: str) -> None:
        print(f'\033[1;32m{text}\033[0m')

    @staticmethod
    def bold_yellow(text: str) -> None:
        print(f'\033[1;33m{text}\033[0m')

    @staticmethod
    def bold_blue(text: str) -> None:
        print(f'\033[1;34m{text}\033[0m')

    @staticmethod
    def bold_cyan(text: str) -> None:
        print(f'\033[1;36m{text}\033[0m')

    @staticmethod
    def format_red(text: str) -> str:
        return f'\033[31m{text}\033[0m'

    @staticmethod
    def format_green(text: str) -> str:
        return f'\033[32m{text}\033[0m'

    @staticmethod
    def format_yellow(text: str) -> str:
        return f'\033[33m{text}\033[0m'

    @staticmethod
    def format_blue(text: str) -> str:
        return f'\033[34m{text}\033[0m'

    @staticmethod
    def format_cyan(text: str) -> str:
        return f'\033[36m{text}\033[0m'

    @staticmethod
    def format_bold(text: str) -> str:
        return f'\033[1m{text}\033[0m'

    @staticmethod
    def format_bold_red(text: str) -> str:
        return f'\033[1;31m{text}\033[0m'

    @staticmethod
    def format_bold_green(text: str) -> str:
        return f'\033[1;32m{text}\033[0m'

    @staticmethod
    def format_bold_yellow(text: str) -> str:
        return f'\033[1;33m{text}\033[0m'

    @staticmethod
    def format_bold_blue(text: str) -> str:
        return f'\033[1;34m{text}\033[0m'

    @staticmethod
    def format_bold_cyan(text: str) -> str:
        return f'\033[1;36m{text}\033[0m'


color = ColorPrinter()


class NicQueueConfig:
    def __init__(self, namespace: Optional[str] = None):
        self.namespace = namespace if namespace and namespace != "none" else None

    def run_cmd(self, cmd: List[str], capture_output: bool = True, input_text: str = None) -> Tuple[str, str, int]:
        try:
            full_cmd = []
            if self.namespace:
                full_cmd.extend(["ip", "netns", "exec", self.namespace])

            full_cmd.extend(cmd)
            res = subprocess.run(
                full_cmd,
                input=input_text,
                capture_output=capture_output,
                text=True,
                check=False
            )

            return res.stdout.strip(), res.stderr.strip(), res.returncode

        except Exception as e:
            return "", str(e), -1

    def check_namespace(self) -> bool:
        if not self.namespace:
            return True
        out, _, ret = self.run_cmd(["ip", "netns", "list"])
        return ret == 0 and self.namespace in out

    def check_nic(self, nic: str) -> bool:
        _, _, ret = self.run_cmd(["ls", f"/sys/class/net/{nic}"])
        return ret == 0

    def parse_range(self, range_str: str) -> List[int]:
        res = []
        parts = [p.strip() for p in range_str.split(',') if p.strip()]
        for part in parts:
            if '-' in part:
                match = re.match(r"^(\d+)-(\d+)$", part)
                if not match:
                    raise ValueError(f"无效范围格式: {part}")
                start, end = map(int, match.groups())
                if start > end:
                    raise ValueError(f"起始>结束: {part}")
                res.extend(range(start, end + 1))
            else:
                if not part.isdigit():
                    raise ValueError(f"无效数字: {part}")
                res.append(int(part))

        return sorted(list(set(res)))

    def expand_all_cpus(self, cpu_str: str) -> List[int]:
        return self.parse_range(cpu_str)

    def generate_mask(self, cpus: List[int], orig_mask: str) -> str:
        segs = orig_mask.split(',')
        if not re.match(r'^([0-9a-fA-F]{8},)*[0-9a-fA-F]{8}$', orig_mask):
            raise ValueError(f"无效掩码格式: {orig_mask}")

        seg_values = [0] * len(segs)

        for cpu in cpus:
            cpu_grp = cpu // 32
            bit_pos = cpu % 32
            seg_idx = len(segs) - 1 - cpu_grp
            if seg_idx < 0 or seg_idx >= len(seg_values):
                raise ValueError(f"CPU {cpu} 超出掩码范围（最大支持CPU: {(len(seg_values)-1)*32 + 31}）")
            seg_values[seg_idx] |= 1 << bit_pos

        new_segs = [f"{val:08x}" for val in seg_values]

        return ','.join(new_segs)

    def mask_to_cpus(self, mask: str) -> List[int]:
        cpus = []
        segs = mask.split(',')
        for grp_idx, seg in enumerate(reversed(segs)):
            seg_val = int(seg, 16)
            for bit in range(32):
                if seg_val & (1 << bit):
                    cpus.append(grp_idx * 32 + bit)

        return sorted(cpus)

    def get_tx_queue_count(self, nic: str) -> int:
        q_path = f"/sys/class/net/{nic}/queues/"
        out, _, ret = self.run_cmd(["ls", q_path])
        if ret != 0:
            raise RuntimeError(f"无法访问队列目录: {q_path}")

        tx_queues = [q for q in out.split() if q.startswith("tx-")]
        if not tx_queues:
            raise RuntimeError(f"未找到TX队列: {q_path}")

        q_nums = []
        for q in tx_queues:
            match = re.match(r"tx-(\d+)", q)
            if match:
                q_nums.append(int(match.group(1)))

        return max(q_nums) + 1 if q_nums else 0

    def get_rx_queue_count(self, nic: str) -> int:
        q_path = f"/sys/class/net/{nic}/queues/"
        out, _, ret = self.run_cmd(["ls", q_path])
        if ret != 0:
            raise RuntimeError(f"无法访问队列目录: {q_path}")

        rx_queues = [q for q in out.split() if q.startswith("rx-")]
        if not rx_queues:
            raise RuntimeError(f"未找到RX队列: {q_path}")

        q_nums = []
        for q in rx_queues:
            match = re.match(r"rx-(\d+)", q)
            if match:
                q_nums.append(int(match.group(1)))

        return max(q_nums) + 1 if q_nums else 0

    def assign_cpus_to_queues(self, queues: List[int], all_cpus: List[int]) -> Dict[int, List[int]]:
        queue_cnt = len(queues)
        cpu_cnt = len(all_cpus)
        if cpu_cnt == 0:
            raise ValueError("CPU范围不能为空")

        queue_cpu_map = {}
        for i, queue in enumerate(queues):
            assigned_cpu = all_cpus[i % cpu_cnt]
            queue_cpu_map[queue] = [assigned_cpu]

        return queue_cpu_map

    def parse_queue_cpu_map(self, map_str: str) -> Dict[int, List[int]]:
        queue_cpu_map = {}
        pattern = r'([^:]+?)(:{1,2})([^,]+(?:,[^,]+)*)'
        matches = re.finditer(pattern, map_str)

        if not matches:
            if ':' not in map_str:
                raise ValueError(f"无效映射格式: {map_str}")
            else:
                raise ValueError(f"无法解析映射字符串: {map_str}")

        for match in matches:
            queue_part = match.group(1).strip()
            separator = match.group(2)
            cpu_part = match.group(3).strip()
            if not queue_part or not cpu_part:
                raise ValueError(f"无效映射格式: {match.group(0)}")

            queues = self.parse_range(queue_part)
            all_cpus = self.expand_all_cpus(cpu_part)
            if separator == '::':
                for q in queues:
                    if q in queue_cpu_map:
                        raise ValueError(f"队列 {q} 重复配置")
                    queue_cpu_map[q] = all_cpus
            else:
                if len(queues) == 1:
                    queue_cpu_map[queues[0]] = all_cpus
                else:
                    sub_map = self.assign_cpus_to_queues(queues, all_cpus)
                    for q, cpus in sub_map.items():
                        if q in queue_cpu_map:
                            raise ValueError(f"队列 {q} 重复配置")
                        queue_cpu_map[q] = cpus

        if not queue_cpu_map:
            raise ValueError("未配置任何队列-CPU映射")

        return queue_cpu_map

    def parse_queue_flow_map(self, map_str: str) -> Dict[int, int]:
        queue_flow_map = {}

        parts = [p.strip() for p in map_str.split(',') if p.strip()]

        for part in parts:
            if ':' not in part:
                raise ValueError(f"无效flow_cnt格式: {part}")

            queue_part, flow_part = part.split(':', 1)
            queues = self.parse_range(queue_part)
            if not flow_part.isdigit():
                raise ValueError(f"flow_cnt必须为非负整数: {flow_part}")

            flow_val = int(flow_part)
            if flow_val < 0:
                raise ValueError(f"flow_cnt不能为负数: {flow_val}")

            for q in queues:
                if q in queue_flow_map:
                    raise ValueError(f"队列 {q} flow_cnt重复配置")
                queue_flow_map[q] = flow_val

        if not queue_flow_map:
            raise ValueError("无效flow_cnt格式")

        return queue_flow_map

    def get_xps_mask(self, nic: str, queue: int) -> str:
        path = f"/sys/class/net/{nic}/queues/tx-{queue}/xps_cpus"
        out, err, ret = self.run_cmd(["cat", path])
        if ret != 0:
            raise RuntimeError(f"读取XPS掩码失败: {err}")
        return out.strip()

    def set_xps_mask(self, nic: str, queue: int, mask: str) -> bool:
        path = f"/sys/class/net/{nic}/queues/tx-{queue}/xps_cpus"
        if self.namespace:
            cmd = ["bash", "-c", f"echo {mask} | sudo tee {path} > /dev/null"]
        else:
            cmd = ["sudo", "tee", path]

        _, _, ret = self.run_cmd(cmd, input_text=mask)

        return ret == 0

    def config_xps_queue(self, nic: str, queue: int, cpus: List[int]) -> bool:
        try:
            curr_mask = self.get_xps_mask(nic, queue)
            new_mask = self.generate_mask(cpus, curr_mask)
            success = self.set_xps_mask(nic, queue, new_mask)
            if success:
                print(f"  {color.format_green(f'队列 {queue}: 成功绑定CPU {cpus}')}")
            else:
                print(f"  {color.format_red(f'队列 {queue}: 绑定失败')}")
            return success

        except Exception as e:
            print(f"  {color.format_red(f'队列 {queue}: 错误 - {str(e)}')}")
            return False

    def config_xps(self, nic: str, cpu_range: str, queue_str: Optional[str] = None) -> Tuple[List[int], List[int]]:
        color.bold_blue(f"配置网卡 {nic} XPS (命名空间 {self.namespace or 'none'})...")
        print()
        if not self.check_nic(nic):
            raise RuntimeError(f"网卡 {nic} 不存在")

        total_queue = self.get_tx_queue_count(nic)
        all_queues = list(range(total_queue))
        target_queues = []
        queue_cpu_map = {}
        if queue_str:
            queue_cpu_map = self.parse_queue_cpu_map(queue_str)
            target_queues = sorted(queue_cpu_map.keys())
            for q in target_queues:
                if q < 0 or q >= total_queue:
                    raise ValueError(f"队列 {q} 超出范围 (0-{total_queue-1})")
        else:
            cpus = self.parse_range(cpu_range)
            if not cpus:
                raise ValueError("CPU范围不能为空")

            target_queues = all_queues
            queue_cnt = len(target_queues)
            cpu_cnt = len(cpus)
            color.cyan(f"未指定队列-CPU映射，配置所有 {queue_cnt} 个队列")
            print()

            if cpu_cnt != queue_cnt:
                color.yellow(f"警告: CPU数({cpu_cnt})与队列数({queue_cnt})不匹配!")
                color.yellow("将使用回环方式绑定")
                print()

                while True:
                    confirm = input(f"{color.format_cyan('是否继续执行? [y/N]: ')}").strip().lower()
                    if confirm in ['y', 'yes']:
                        break
                    elif confirm in ['n', 'no', '']:
                        color.yellow("操作已取消")
                        return [], list(range(total_queue))
                    else:
                        color.red("请输入 y 或 n")

            for idx, q in enumerate(target_queues):
                queue_cpu_map[q] = [cpus[idx % cpu_cnt]]

        ok_queues = []
        fail_queues = []
        for queue in target_queues:
            cpus = queue_cpu_map[queue]
            if self.config_xps_queue(nic, queue, cpus):
                ok_queues.append(queue)
            else:
                fail_queues.append(queue)

        return ok_queues, fail_queues

    def _format_cpu_lines(self, cpus: List[int]) -> List[str]:
        if not cpus:
            return []

        chunks = [cpus[i:i+19] for i in range(0, len(cpus), 19)]
        return [' '.join(map(str, chunk)) for chunk in chunks]

    def _print_queue_cpus(self, queue_label: str, cpus: List[int], indent: int = 8) -> None:
        queue_padded = queue_label.ljust(indent + 9)
        if not cpus:
            print(f"{queue_padded} {color.format_yellow('未绑定')}")
            return

        cpu_lines = self._format_cpu_lines(cpus)
        print(f"{queue_padded} {color.format_green(cpu_lines[0])}")
        for line in cpu_lines[1:]:
            print(f"{'':<{indent}} {color.format_green(line)}")

    def read_xps(self, nic: str, queue_str: Optional[str] = None) -> None:
        color.bold_blue(f"读取网卡 {nic} XPS 绑定信息 (命名空间 {self.namespace or 'none'})")
        print()

        if not self.check_nic(nic):
            raise RuntimeError(f"网卡 {nic} 不存在")

        total_queue = self.get_tx_queue_count(nic)
        all_queues = list(range(total_queue))
        target_queues = []
        if queue_str:
            if ':' in queue_str:
                queue_cpu_map = self.parse_queue_cpu_map(queue_str)
                target_queues = sorted(queue_cpu_map.keys())
            else:
                target_queues = self.parse_range(queue_str)
            for q in target_queues:
                if q < 0 or q >= total_queue:
                    raise ValueError(f"队列 {q} 超出范围 (0-{total_queue-1})")
        else:
            target_queues = all_queues

        for queue in target_queues:
            try:
                mask = self.get_xps_mask(nic, queue)
                cpus = self.mask_to_cpus(mask)
                queue_label = color.format_cyan(f"txq {queue}")
                self._print_queue_cpus(queue_label, cpus)
            except Exception as e:
                queue_label = color.format_cyan(f"txq {queue}")
                queue_padded = queue_label.ljust(8)
                print(f"{queue_padded}    {color.format_red(f'读取失败 - {str(e)}')}")

    def get_rps_mask(self, nic: str, queue: int) -> str:
        path = f"/sys/class/net/{nic}/queues/rx-{queue}/rps_cpus"
        out, err, ret = self.run_cmd(["cat", path])
        if ret != 0:
            raise RuntimeError(f"读取RPS掩码失败: {err}")

        return out.strip()

    def set_rps_mask(self, nic: str, queue: int, mask: str) -> bool:
        path = f"/sys/class/net/{nic}/queues/rx-{queue}/rps_cpus"
        if self.namespace:
            cmd = ["bash", "-c", f"echo {mask} | sudo tee {path} > /dev/null"]
        else:
            cmd = ["sudo", "tee", path]

        _, _, ret = self.run_cmd(cmd, input_text=mask)

        return ret == 0

    def get_flow_cnt(self, nic: str, queue: int) -> int:
        path = f"/sys/class/net/{nic}/queues/rx-{queue}/rps_flow_cnt"
        out, err, ret = self.run_cmd(["cat", path])

        if ret != 0:
            raise RuntimeError(f"读取rps_flow_cnt失败: {err}")

        if not out.isdigit():
            raise RuntimeError(f"rps_flow_cnt值无效: {out}")

        return int(out.strip())

    def set_flow_cnt(self, nic: str, queue: int, flow_val: int) -> bool:
        if flow_val < 0:
            print(f"  {color.format_red(f'队列 {queue}: flow_cnt不能为负数')}")
            return False

        path = f"/sys/class/net/{nic}/queues/rx-{queue}/rps_flow_cnt"
        if self.namespace:
            cmd = ["bash", "-c", f"echo {flow_val} | sudo tee {path} > /dev_null"]
        else:
            cmd = ["sudo", "tee", path]
        _, _, ret = self.run_cmd(cmd, input_text=str(flow_val))

        return ret == 0

    def config_rps_queue(self, nic: str, queue: int, cpus: Optional[List[int]] = None, flow_val: Optional[int] = None) -> bool:
        try:
            success = True
            if cpus is not None:
                curr_mask = self.get_rps_mask(nic, queue)
                new_mask = self.generate_mask(cpus, curr_mask)

                if not self.set_rps_mask(nic, queue, new_mask):
                    success = False
                    print(f"  {color.format_red(f'队列 {queue}: RPS掩码设置失败')}")
                else:
                    print(f"  {color.format_green(f'队列 {queue}: 成功绑定CPU {cpus}')}")

            if flow_val is not None:
                if not self.set_flow_cnt(nic, queue, flow_val):
                    success = False
                    print(f"  {color.format_red(f'队列 {queue}: rps_flow_cnt设置失败')}")
                else:
                    print(f"  {color.format_green(f'队列 {queue}: rps_flow_cnt={flow_val} 设置成功')}")

            return success
        except Exception as e:
            print(f"  {color.format_red(f'队列 {queue}: 错误 - {str(e)}')}")
            return False

    def config_rps(self, nic: str, cpu_range: Optional[str] = None, queue_str: Optional[str] = None, flow_str: Optional[str] = None) -> Tuple[List[int], List[int]]:
        color.bold_blue(f"配置网卡 {nic} RPS (命名空间 {self.namespace or 'none'})...")
        print()

        if not self.check_nic(nic):
            raise RuntimeError(f"网卡 {nic} 不存在")

        total_queue = self.get_rx_queue_count(nic)
        all_queues = list(range(total_queue))
        target_queues = []
        queue_cpu_map = {}
        queue_flow_map = {}
        only_flow = False

        if flow_str:
            queue_flow_map = self.parse_queue_flow_map(flow_str)
            target_queues = sorted(queue_flow_map.keys())
            for q in target_queues:
                if q < 0 or q >= total_queue:
                    raise ValueError(f"队列 {q} 超出范围 (0-{total_queue-1})")

        if queue_str:
            queue_cpu_map = self.parse_queue_cpu_map(queue_str)
            cpu_queues = sorted(queue_cpu_map.keys())
            for q in cpu_queues:
                if q < 0 or q >= total_queue:
                    raise ValueError(f"队列 {q} 超出范围 (0-{total_queue-1})")

            if flow_str:
                flow_queues = set(queue_flow_map.keys())
                cpu_queues_set = set(cpu_queues)
                if flow_queues != cpu_queues_set:
                    missing = cpu_queues_set - flow_queues
                    extra = flow_queues - cpu_queues_set
                    err_msg = []
                    if missing:
                        err_msg.append(f"缺失flow_cnt配置的队列: {','.join(map(str, missing))}")
                    if extra:
                        err_msg.append(f"多余flow_cnt配置的队列: {','.join(map(str, extra))}")

                    raise ValueError("; ".join(err_msg))

            target_queues = cpu_queues

        if cpu_range and not queue_str and not only_flow:
            cpus = self.parse_range(cpu_range)
            if not cpus:
                raise ValueError("CPU范围不能为空")
            target_queues = all_queues
            queue_cnt = len(target_queues)
            cpu_cnt = len(cpus)
            color.cyan(f"未指定队列-CPU映射，配置所有 {queue_cnt} 个队列")
            print()

            if cpu_cnt != queue_cnt:
                color.yellow(f"警告: CPU数({cpu_cnt})与队列数({queue_cnt})不匹配!")
                color.yellow("将使用回环绑定")
                print()

                while True:
                    confirm = input(f"{color.format_cyan('是否继续执行? [y/N]: ')}").strip().lower()
                    if confirm in ['y', 'yes']:
                        break
                    elif confirm in ['n', 'no', '']:
                        color.yellow("操作已取消")
                        return [], list(range(total_queue))
                    else:
                        color.red("请输入 y 或 n")

            for idx, q in enumerate(target_queues):
                queue_cpu_map[q] = [cpus[idx % cpu_cnt]]

        if not queue_cpu_map and flow_str:
            only_flow = True
            color.cyan("仅配置rps_flow_cnt，不修改RPS CPU绑定")
            print()

        if not target_queues:
            target_queues = all_queues

        ok_queues = []
        fail_queues = []
        for queue in target_queues:
            cpus = queue_cpu_map.get(queue) if not only_flow else None
            flow_val = queue_flow_map.get(queue) if flow_str else None
            if self.config_rps_queue(nic, queue, cpus, flow_val):
                ok_queues.append(queue)
            else:
                fail_queues.append(queue)

        return ok_queues, fail_queues

    def read_rps(self, nic: str, queue_str: Optional[str] = None) -> None:
        color.bold_blue(f"读取网卡 {nic} RPS 绑定信息 (命名空间 {self.namespace or 'none'})...")
        print()

        if not self.check_nic(nic):
            raise RuntimeError(f"网卡 {nic} 不存在")

        total_queue = self.get_rx_queue_count(nic)
        all_queues = list(range(total_queue))
        target_queues = []
        if queue_str:
            if ':' in queue_str:
                queue_cpu_map = self.parse_queue_cpu_map(queue_str)
                target_queues = sorted(queue_cpu_map.keys())
            else:
                target_queues = self.parse_range(queue_str)
            for q in target_queues:
                if q < 0 or q >= total_queue:
                    raise ValueError(f"队列 {q} 超出范围 (0-{total_queue-1})")
        else:
            target_queues = all_queues
        
        indent = 9
        for queue in target_queues:
            try:
                mask = self.get_rps_mask(nic, queue)
                cpus = self.mask_to_cpus(mask)
                flow_cnt = self.get_flow_cnt(nic, queue)
                queue_label = color.format_cyan(f"rxq {queue}")
                self._print_queue_cpus(queue_label, cpus)
                if cpus:
                    indent = 9
                    flow_label = color.format_yellow(f"rps_flow_cnt {flow_cnt}")
                    print(f"{'':<{indent}}{flow_label}")
                else:
                    flow_label = color.format_yellow(f"rps_flow_cnt {flow_cnt}")
                    print(f"{'':<{indent}}{flow_label}")
            except Exception as e:
                queue_label = color.format_cyan(f"rxq {queue}")
                queue_padded = queue_label.ljust(indent + 9)
                print(f"{queue_padded}    {color.format_red(f'读取失败 - {str(e)}')}")

    def restore_default(self, nic: str, rps: bool = True) -> Tuple[List[int], List[int]]:
        if rps:
            color.bold_blue(f"恢复网卡 {nic} RPS 默认配置 (命名空间 {self.namespace or 'none'})...")
        else:
            color.bold_blue(f"恢复网卡 {nic} XPS 默认配置 (命名空间 {self.namespace or 'none'})...")
        print()

        if not self.check_nic(nic):
            raise RuntimeError(f"网卡 {nic} 不存在")

        if rps:
            total_queue = self.get_rx_queue_count(nic)
            queues = list(range(total_queue))
        else:
            total_queue = self.get_tx_queue_count(nic)
            queues = list(range(total_queue))

        ok_queues = []
        fail_queues = []
        for queue in queues:
            try:
                if rps:
                    mask = "0"
                    path = f"/sys/class/net/{nic}/queues/rx-{queue}/rps_cpus"
                    if self.namespace:
                        cmd = ["bash", "-c", f"echo {mask} | sudo tee {path} > /dev/null"]
                    else:
                        cmd = ["sudo", "tee", path]

                    _, _, ret = self.run_cmd(cmd, input_text=mask)
                    if ret == 0:
                        ok_queues.append(queue)
                        print(f"  {color.format_green(f'队列 {queue}: 恢复成功')}")
                    else:
                        fail_queues.append(queue)
                        print(f"  {color.format_red(f'队列 {queue}: 恢复失败')}")
                else:
                    mask = "0"
                    path = f"/sys/class/net/{nic}/queues/tx-{queue}/xps_cpus"
                    if self.namespace:
                        cmd = ["bash", "-c", f"echo {mask} | sudo tee {path} > /dev/null"]
                    else:
                        cmd = ["sudo", "tee", path]

                    _, _, ret = self.run_cmd(cmd, input_text=mask)
                    if ret == 0:
                        ok_queues.append(queue)
                        print(f"  {color.format_green(f'队列 {queue}: 恢复成功')}")
                    else:
                        fail_queues.append(queue)
                        print(f"  {color.format_red(f'队列 {queue}: 恢复失败')}")
            except Exception as e:
                print(f"  {color.format_red(f'队列 {queue}: 错误 - {str(e)}')}")
                fail_queues.append(queue)

        return ok_queues, fail_queues


def parse_args():
    parser = argparse.ArgumentParser(
        description="网卡RX/TX队列RPS/XPS配置工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "XPS示例:\n"
            "  配置命名空间ns4的eth4，队列0-31绑定CPU0-31:  %(prog)s -t xps -s ns4 -n eth4 -q 0-31:0-31\n"
            "  配置eth0队列0-62每个都绑定CPU0-55,112-167:  %(prog)s -t xps -n eth0 -q 0-62::0-55,112-167\n"
            "  配置eth0队列0-62按顺序分配CPU0-55,112-167:  %(prog)s -t xps -n eth0 -q 0-62:0-55,112-167\n"
            "\nRPS示例:\n"
            "  配置队列0-62每个都绑定CPU0-55,112-167且flow_cnt=1024:  %(prog)s -t rps -n ens16f0np0 -q 0-62::0-55,112-167 -f 0-62:1024\n"
            "  配置队列0-62按顺序分配CPU0-55,112-167:  %(prog)s -t rps -n ens16f0np0 -q 0-62:0-55,112-167\n"
            "  配置队列0绑定CPU1-4,6-9:  %(prog)s -t rps -n ens16f0np0 -q 0:1,2,3,4,6-9\n"
            "  仅配置所有队列flow_cnt=1024:  %(prog)s -t rps -n ens16f0np0 -f 0-62:1024\n"
            "  读取所有队列RPS绑定信息:  %(prog)s -t rps -r -n ens16f0np0\n"
            "  恢复RPS默认配置:  %(prog)s -t rps -d -n ens16f0np0"
        )
    )
    parser.add_argument("-t", "--type", required=True, choices=['xps', 'rps'], help="配置类型")
    parser.add_argument("-s", "--namespace", default=None, help="网络命名空间")
    parser.add_argument("-r", "--read", action="store_true", help="读取绑定信息")
    parser.add_argument("-d", "--default", action="store_true", help="恢复默认配置")
    parser.add_argument("-q", "--queues", default=None, help="队列-CPU映射")
    parser.add_argument("-f", "--flow-cnt", default=None, help="rps_flow_cnt配置")
    parser.add_argument("-n", "--nic", required=True, help="网卡名称")
    parser.add_argument("cpu_range", nargs='?', help="CPU范围")
    return parser.parse_args()


def check_root():
    if os.geteuid() != 0:
        color.bold_red("错误: 需要root权限，请用sudo运行")
        sys.exit(1)


def main():
    args = parse_args()
    failed = []
    if args.read:
        if args.cpu_range:
            color.yellow("警告: 读取模式下CPU范围参数无效，将忽略")
        if args.flow_cnt:
            color.yellow("警告: 读取模式下flow-cnt参数无效，将忽略")
        if args.default:
            color.bold_red("错误: 读取模式和恢复默认模式不能同时使用")
            sys.exit(1)
    elif args.default:
        if args.cpu_range:
            color.yellow("警告: 恢复默认模式下CPU范围参数无效，将忽略")
        if args.queues:
            color.yellow("警告: 恢复默认模式下队列映射参数无效，将忽略")
        if args.flow_cnt:
            color.yellow("警告: 恢复默认模式下flow-cnt参数无效，将忽略")
    else:
        if args.type == 'xps':
            if args.flow_cnt:
                color.yellow("警告: XPS模式不支持flow-cnt参数，将忽略")
            if not args.queues and not args.cpu_range:
                color.bold_red("错误: XPS模式需指定CPU范围参数")
                sys.exit(1)
        else:
            if not args.queues and not args.cpu_range and not args.flow_cnt:
                color.bold_red("错误: 需指定CPU范围或flow-cnt参数")
                sys.exit(1)
            if args.queues and args.cpu_range:
                color.yellow("警告: 映射模式下CPU范围参数无效，将忽略")
    if not args.namespace and not args.read and not args.default:
        check_root()
    config = NicQueueConfig(args.namespace)
    try:
        if args.namespace and not config.check_namespace():
            color.bold_red(f"错误: 命名空间 '{args.namespace}' 不存在")
            sys.exit(1)
        if args.read:
            if args.type == 'xps':
                config.read_xps(args.nic, args.queues)
            else:
                config.read_rps(args.nic, args.queues)
        elif args.default:
            ok_queues, failed = config.restore_default(args.nic, args.type == 'rps')
            print()
            color.bold("执行结果:")
            color.green(f"  成功队列: {len(ok_queues)} 个")
            if ok_queues:
                color.green(f"  成功列表: {','.join(map(str, ok_queues))}")
            color.red(f"  失败队列: {len(failed)} 个")
            if failed:
                color.red(f"  失败列表: {','.join(map(str, failed))}")
        else:
            if args.type == 'xps':
                ok_queues, failed = config.config_xps(args.nic, args.cpu_range, args.queues)
            else:
                ok_queues, failed = config.config_rps(args.nic, args.cpu_range, args.queues, args.flow_cnt)
            print()
            color.bold("执行结果:")
            color.green(f"  成功队列: {len(ok_queues)} 个")
            if ok_queues:
                color.green(f"  成功列表: {','.join(map(str, ok_queues))}")
            color.red(f"  失败队列: {len(failed)} 个")
            if failed:
                color.red(f"  失败列表: {','.join(map(str, failed))}")
        sys.exit(0 if not failed else 1)
    except Exception as e:
        color.bold_red(f"错误: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
