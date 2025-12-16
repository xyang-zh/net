#!/usr/bin/env python3

import sys
import os
import re
import subprocess
import argparse
import time
from typing import Dict, List, Optional, Tuple


class ColorPrinter:
    @staticmethod
    def red(text: str) -> str:
        return f'\033[31m{text}\033[0m'

    @staticmethod
    def green(text: str) -> str:
        return f'\033[32m{text}\033[0m'

    @staticmethod
    def yellow(text: str) -> str:
        return f'\033[33m{text}\033[0m'

    @staticmethod
    def blue(text: str) -> str:
        return f'\033[34m{text}\033[0m'

    @staticmethod
    def cyan(text: str) -> str:
        return f'\033[36m{text}\033[0m'

    @staticmethod
    def bold(text: str) -> str:
        return f'\033[1m{text}\033[0m'

    @staticmethod
    def bold_red(text: str) -> str:
        return f'\033[1;31m{text}\033[0m'

    @staticmethod
    def bold_green(text: str) -> str:
        return f'\033[1;32m{text}\033[0m'

    @staticmethod
    def bold_yellow(text: str) -> str:
        return f'\033[1;33m{text}\033[0m'

    @staticmethod
    def bold_blue(text: str) -> str:
        return f'\033[1;34m{text}\033[0m'

    @staticmethod
    def bold_cyan(text: str) -> str:
        return f'\033[1;36m{text}\033[0m'


class IrqCpuBinder:
    def __init__(self, namespace: Optional[str], device: str, cpu_range: Optional[str], mode: Optional[str]):
        self.namespace = namespace
        self.device = device
        self.cpu_range = cpu_range
        self.mode = mode
        self.color = ColorPrinter()

    def run_cmd(self, cmd: str, check: bool = True) -> str:
        try:
            if self.namespace:
                cmd = f"ip netns exec {self.namespace} {cmd}"
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=check
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            return ""

    def check_root(self) -> None:
        if os.geteuid() != 0:
            print(self.color.bold_red("错误：需root权限运行！"))
            sys.exit(1)

    def validate_cpu_range(self) -> Tuple[int, int, List[int]]:
        if not re.match(r'^[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*$', self.cpu_range):
            print(self.color.bold_red("错误：CPU范围格式错误（支持格式：0-31 或 0,2-4,6）"))
            sys.exit(1)

        cpu_list = []
        for part in self.cpu_range.split(','):
            if '-' in part:
                start, end = map(int, part.split('-'))
                if start > end:
                    print(self.color.bold_red(f"错误：CPU范围无效（{start} > {end}）"))
                    sys.exit(1)
                cpu_list.extend(range(start, end + 1))
            else:
                cpu_list.append(int(part))

        max_cpu = int(self.run_cmd("grep -c ^processor /proc/cpuinfo"))
        for cpu in cpu_list:
            if cpu >= max_cpu:
                print(self.color.bold_red(f"错误：系统最大CPU编号 {max_cpu - 1}（共{max_cpu}个CPU）"))
                sys.exit(1)

        return min(cpu_list), max(cpu_list), sorted(list(set(cpu_list)))

    def get_bus_info(self) -> str:
        cmd = f"ethtool -i {self.device} 2>/dev/null | grep -E '^bus-info:' | awk -F 'bus-info:' '{{print $2}}' | xargs"
        bus_info = self.run_cmd(cmd)
        if not bus_info:
            err_msg = f"错误：无法获取网卡 {self.device} 的bus-info"
            if self.namespace:
                err_msg += f"（命名空间：{self.namespace}）"
            print(self.color.bold_red(err_msg))
            sys.exit(1)

        return bus_info

    def get_driver_type(self) -> str:
        cmd = f"ethtool -i {self.device} 2>/dev/null | grep -E '^driver:' | awk -F 'driver:' '{{print $2}}' | xargs"
        return self.run_cmd(cmd)

    def is_virtio_irq(self, irq_desc: str) -> bool:
        return 'virtio' in irq_desc.lower()

    def get_virtio_irq_type(self, irq_desc: str) -> str:
        irq_desc_lower = irq_desc.lower()
        if 'input' in irq_desc_lower:
            return 'input'
        elif 'output' in irq_desc_lower:
            return 'output'
        return 'unknown'

    def get_irq_map(self, bus_info: str) -> Dict[int, str]:
        irq_map = {}
        msi_irqs_path = f"/sys/bus/pci/devices/{bus_info}/msi_irqs"

        if not os.path.exists(msi_irqs_path):
            print(self.color.bold_red(f"错误：未找到MSI中断目录：{msi_irqs_path}"))
            sys.exit(1)

        irq_list = []
        for item in os.listdir(msi_irqs_path):
            if item.isdigit():
                irq_list.append(int(item))
        irq_list.sort()

        if not irq_list:
            print(self.color.bold_red(f"错误：未在{msi_irqs_path}找到中断号"))
            sys.exit(1)

        with open("/proc/interrupts", "r") as f:
            interrupt_lines = f.readlines()

        for irq in irq_list:
            irq_desc = ""

            for line in interrupt_lines:
                if line.strip().startswith(f"{irq}:"):
                    parts = line.strip().split()
                    if parts:
                        irq_desc = parts[-1]
                    break
            
            irq_map[irq] = irq_desc if irq_desc else f"irq-{irq}"

        return irq_map

    def bind_irq_to_cpu(self, irq_map: Dict[int, str], cpu_list: List[int], driver_type: str) -> None:
        irq_list = list(irq_map.keys())
        cpu_count = len(cpu_list)

        is_virtio_driver = driver_type.lower() == 'virtio_net'
        valid_irqs = []

        for irq in irq_list:
            irq_desc = irq_map[irq]
            if is_virtio_driver:
                irq_type = self.get_virtio_irq_type(irq_desc)
                if irq_type == 'input':
                    valid_irqs.append(irq)
            else:
                valid_irqs.append(irq)

        valid_irq_count = len(valid_irqs)
        
        if valid_irq_count == 0:
            print(self.color.bold_red("错误：无符合条件的有效中断，无法进行绑定！"))
            return

        min_count = min(valid_irq_count, cpu_count)
        target_irqs = valid_irqs[:min_count]
        target_cpus = cpu_list[:min_count]

        if valid_irq_count > cpu_count:
            print(self.color.yellow(f"警告： 中断数({valid_irq_count})大于CPU数({cpu_count})，截断为{min_count}个"))
        elif cpu_count > valid_irq_count:
            print(self.color.yellow(f"警告： CPU数({cpu_count})大于中断数({valid_irq_count})，截断为{min_count}个"))
        print()

        for irq, target_cpu in zip(target_irqs, target_cpus):
            irq_desc = irq_map[irq]
            irq_path = f"/proc/irq/{irq}/smp_affinity_list"

            if not os.path.exists(irq_path):
                print(self.color.red(f"中断{irq}（{irq_desc}）：路径不存在，跳过"))
                continue

            try:
                with open(irq_path, "w") as f:
                    f.write(str(target_cpu))

                with open(irq_path, "r") as f:
                    bind_result = f.read().strip()

                if bind_result != str(target_cpu):
                    print(self.color.red(f"中断{irq}（{irq_desc}）：绑定失败（实际：{bind_result}）"))
                else:
                    msix = self.color.cyan(f"msi-x {irq}")
                    irq_str = self.color.yellow(f"({irq_desc})")
                    cpu = self.color.green(f"cpu {target_cpu}")
                    print(f"{msix} {irq_str}  {cpu}")

            except Exception as e:
                print(self.color.red(f"中断{irq}（{irq_desc}）：绑定失败（错误：{str(e)}）"))

    def _show_single_irq_bind(self, irq: int, irq_desc: str) -> None:
        irq_path = f"/proc/irq/{irq}/smp_affinity_list"
        if not os.path.exists(irq_path):
            print(f"msi-x {self.color.cyan(irq)} ({self.color.yellow(irq_desc)})：{self.color.red('设备不存在')}")
            return

        try:
            with open(irq_path, "r") as f:
                current_cpu = f.read().strip()
            
            msix = self.color.cyan(f"msi-x {irq}")
            irq_desc = self.color.yellow(f"({irq_desc})")
            cpu = self.color.green(f" cpu {current_cpu}")
            print(f"{msix} {irq_desc} {cpu}")

        except Exception as e:
            print(f"msi-x {self.color.cyan(irq)} ({self.color.yellow(irq_desc)})：{self.color.red(f'读取失败（{str(e)}）')}")

    def _read_bind_relation(self, driver_type: str, irq_map: Dict[int, str]) -> None:
        is_virtio = any(self.is_virtio_irq(desc) for desc in irq_map.values())
        
        say = f"网卡：{self.color.cyan(self.device)}    驱动：{self.color.cyan(driver_type)}"
        if self.namespace:
            say += f"    命名空间：{self.color.cyan(self.namespace)}"
        say += f"    中断数：{self.color.cyan(len(irq_map))}"
        print(say)
        print()

        if is_virtio:
            virtio_input = []
            virtio_output = []
            others = []
            
            for irq, irq_desc in irq_map.items():
                if self.is_virtio_irq(irq_desc):
                    irq_type = self.get_virtio_irq_type(irq_desc)
                    if irq_type == 'input':
                        virtio_input.append((irq, irq_desc))
                    elif irq_type == 'output':
                        virtio_output.append((irq, irq_desc))
                    else:
                        others.append((irq, irq_desc))
                else:
                    others.append((irq, irq_desc))
            
            virtio_input.sort(key=lambda x: x[0])
            virtio_output.sort(key=lambda x: x[0])
            others.sort(key=lambda x: x[0])
            
            for irq, irq_desc in virtio_input:
                self._show_single_irq_bind(irq, irq_desc)
            print()

            for irq, irq_desc in virtio_output:
                self._show_single_irq_bind(irq, irq_desc)
            
            print()
            for irq, irq_desc in others:
                self._show_single_irq_bind(irq, irq_desc)
        else:
            sorted_irqs = sorted(irq_map.items(), key=lambda x: x[0])
            for irq, irq_desc in sorted_irqs:
                self._show_single_irq_bind(irq, irq_desc)

    def get_irq_cpus(self, irq: int) -> List[int]:
        irq_path = f"/proc/irq/{irq}/smp_affinity_list"
        if not os.path.exists(irq_path):
            return []
        
        with open(irq_path, "r") as f:
            cpu_str = f.read().strip()
        
        cpus = []
        for part in cpu_str.split(','):
            if '-' in part:
                s, e = map(int, part.split('-'))
                cpus.extend(range(s, e + 1))
            else:
                cpus.append(int(part))
        
        return sorted(cpus)

    def get_per_cpu_count(self, irq: int) -> Optional[List[int]]:
        count_path = f"/sys/kernel/irq/{irq}/per_cpu_count"
        if not os.path.exists(count_path):
            return None
        
        with open(count_path, "r") as f:
            return list(map(int, f.read().strip().split(',')))

    def show_irq_speed(self, irq_items: List[Tuple[int, str]], irq_cpus: Dict[int, List[int]], speed_data: Dict[int, Optional[List[int]]]):
        CPU_PER_LINE = 3
        BASE_INDENT = 30
        SEPARATOR = "   "

        for irq_num, irq_desc in irq_items:
            cpus = irq_cpus[irq_num]
            speeds = speed_data[irq_num]
            if not cpus or speeds is None:
                msi_part = self.color.cyan(f"msi-x {irq_num}")
                irq_desc_str = self.color.yellow(f"({irq_desc})")

                base_info = f"{msi_part} {irq_desc_str}"
                visible_len = len(re.sub(r'\033\[[0-9;]*m', '', base_info))
                
                padding = max(0, BASE_INDENT - visible_len)
                print(f"{base_info}{' ' * padding}：{self.color.red('无法测量')}")
                
                continue
        
            cpu_speed_list = []
            for cpu in cpus:
                cpu_str = self.color.green(f"cpu {cpu}")
                if cpu >= len(speeds):
                    cpu_speed_list.append(f"{cpu_str} {self.color.red('无效索引')}")
                else:
                    cpu_speed_list.append(f"{cpu_str} {self.color.yellow(str(speeds[cpu]))}")
        
            msi_part = self.color.cyan(f"msi-x {irq_num}")
            irq_desc_str = self.color.yellow(f"({irq_desc})")
            base_info = f"{msi_part} {irq_desc_str}"
        
            first_line_cpu_count = min(CPU_PER_LINE, len(cpu_speed_list))
            first_line_cpus = SEPARATOR.join(cpu_speed_list[:first_line_cpu_count])
        
            visible_len = len(re.sub(r'\033\[[0-9;]*m', '', base_info))
            padding = max(0, BASE_INDENT - visible_len)
        
            print(f"{base_info}{' ' * padding}{SEPARATOR}{first_line_cpus}")
        
            remaining_cpus = cpu_speed_list[first_line_cpu_count:]
            total_indent = BASE_INDENT + len(SEPARATOR)
            for i in range(0, len(remaining_cpus), CPU_PER_LINE):
                line_cpus = SEPARATOR.join(remaining_cpus[i:i+CPU_PER_LINE])
                print(f"{'':<{total_indent}}{line_cpus}")

    def _measure_irq_speed(self, driver_type: str, irq_map: Dict[int, str]) -> None:
        say = f"网卡：{self.color.cyan(self.device)}    驱动：{self.color.cyan(driver_type)}"
        if self.namespace:
            say += f"    命名空间：{self.color.cyan(self.namespace)}"
        say += f"    中断数：{self.color.cyan(len(irq_map))}"
        print(say)
        print()

        irq_cpus: Dict[int, List[int]] = {}
        for irq in irq_map:
            irq_cpus[irq] = self.get_irq_cpus(irq)

        initial_counts: Dict[int, Optional[List[int]]] = {}
        for irq in irq_map:
            initial_counts[irq] = self.get_per_cpu_count(irq)

        time.sleep(1)

        final_counts: Dict[int, Optional[List[int]]] = {}
        for irq in irq_map:
            final_counts[irq] = self.get_per_cpu_count(irq)

        speed_data: Dict[int, Optional[List[int]]] = {}
        for irq in irq_map:
            initial = initial_counts[irq]
            final = final_counts[irq]
            if initial is None or final is None or len(initial) != len(final):
                speed_data[irq] = None
                continue

            speed_data[irq] = [final[i] - initial[i] for i in range(len(initial))]

        is_virtio = any(self.is_virtio_irq(desc) for desc in irq_map.values())
        if is_virtio:
            virtio_input = []
            virtio_output = []
            others = []
            
            for irq, irq_desc in irq_map.items():
                if self.is_virtio_irq(irq_desc):
                    irq_type = self.get_virtio_irq_type(irq_desc)
                    if irq_type == 'input':
                        virtio_input.append((irq, irq_desc))
                    elif irq_type == 'output':
                        virtio_output.append((irq, irq_desc))
                    else:
                        others.append((irq, irq_desc))
                else:
                    others.append((irq, irq_desc))
            
            virtio_input.sort(key=lambda x: x[0])
            virtio_output.sort(key=lambda x: x[0])
            others.sort(key=lambda x: x[0])

            for category in [virtio_input, virtio_output, others]:
                if category:
                    self.show_irq_speed(category, irq_cpus, speed_data)
                    print()
        else:
            sorted_irqs = sorted(irq_map.items(), key=lambda x: x[0])
            self.show_irq_speed(sorted_irqs, irq_cpus, speed_data)

    def _print_bind_info(self, driver_type: str, bus_info: str, irq_map: Dict[int, str], cpu_list: Optional[List[int]] = None) -> None:
        info = ""
        if self.namespace:
            info += f"空间：{self.color.cyan(self.namespace)}    "
        info += f"网卡：{self.color.cyan(self.device)}    "
        print(info)

        info = ""
        info += f"驱动：{self.color.cyan(driver_type)}    "
        info += f"PCI号：{self.color.cyan(bus_info)}    "
        info += f"中断数：{self.color.cyan(len(irq_map))}   "
        if cpu_list:
            info += f"绑定CPU：{self.color.cyan(f'{cpu_list[0]}-{cpu_list[-1]}')}"
        print(info)

    def run(self) -> None:
        self.check_root()

        bus_info = self.get_bus_info()
        driver_type = self.get_driver_type()
        irq_map = self.get_irq_map(bus_info)

        if self.mode == 'read':
            self._read_bind_relation(driver_type, irq_map)
        elif self.mode == 'measure':
            self._measure_irq_speed(driver_type, irq_map)
        else:
            cpu_start, cpu_end, cpu_list = self.validate_cpu_range()
            self._print_bind_info(driver_type, bus_info, irq_map, cpu_list)
            self.bind_irq_to_cpu(irq_map, cpu_list, driver_type)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="网卡中断绑定CPU工具（-r读中断，-x测试）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例：
  绑定（非命名空间）：%(prog)s -n eth4 -c 0-31
  绑定（命名空间）：%(prog)s -s ns4 -n eth4 -c 0-31
  只读分类显示：%(prog)s -r -n eth4
  测速：%(prog)s -m -n eth4"""
    )
    
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument('-r', '--read', action='store_true', help='分类显示中断-CPU绑定关系')
    mode_group.add_argument('-x', '--ex', action='store_true', help='测量中断速度，每秒计数')
    
    parser.add_argument('-s', '--namespace', help='网络命名空间名称（可选）')
    parser.add_argument('-n', '--device', required=True, help='网卡名称（必填，如eth4）')
    parser.add_argument('-c', '--cpu-range', help='CPU范围（绑定模式必填，支持格式：0-31 或 0,2-4,6）')

    args = parser.parse_args()

    if args.read and args.ex:
        parser.error("参数 -r 和 -m 不能同时使用，请二选一")
    
    if not args.read and not args.ex and not args.cpu_range:
        parser.error("绑定必须指定 -c/--cpu-range 参数（如：-c 0-31 或 -c 0,2-4）")

    return args


def main() -> None:
    args = parse_args()
    
    mode = None
    if args.read:
        mode = 'read'
    elif args.ex:
        mode = 'measure'

    binder = IrqCpuBinder(
        namespace=args.namespace,
        device=args.device,
        cpu_range=args.cpu_range,
        mode=mode
    )
    binder.run()


if __name__ == "__main__":
    main()
