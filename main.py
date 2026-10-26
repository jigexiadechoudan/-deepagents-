import argparse

from research_agent.workflow import run_extraction


def main():
    parser = argparse.ArgumentParser(description="从材料提取设计模型")
    parser.add_argument("--thinking", action="store_true", help="开启思考模式（默认关闭）")
    args = parser.parse_args()
    run_extraction(thinking=args.thinking)


if __name__ == "__main__":
    main()
