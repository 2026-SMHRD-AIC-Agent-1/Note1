import os

from rag_ai_service_v7 import RagInterviewAI, SCORING_VERSION, JOB_MAX_LEVEL, ANSWER_MAX_LEVEL


HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(HERE, "data")
EXPECTED_PREFIXES = ("02_", "03_", "04_", "05_", "06_", "07_", "08_")


def check_data_files():
    files = sorted(os.listdir(DATA_PATH)) if os.path.isdir(DATA_PATH) else []
    matched = [f for f in files if f.startswith(EXPECTED_PREFIXES)]

    print("[1] V7 버전 확인")
    print("SCORING_VERSION:", SCORING_VERSION)
    print("JOB_MAX_LEVEL:", JOB_MAX_LEVEL)
    print("ANSWER_MAX_LEVEL:", ANSWER_MAX_LEVEL)

    print("\n[2] RAG 자료 확인")
    print("DATA_PATH:", DATA_PATH)
    for f in matched:
        print(" -", f)

    missing = [prefix for prefix in EXPECTED_PREFIXES if not any(f.startswith(prefix) for f in matched)]
    if missing:
        raise RuntimeError(f"RAG 자료 누락: {missing}")
    print("RAG 자료 02~08 확인 완료")


def main():
    check_data_files()

    print("\n[3] RAG 인덱싱")
    ai = RagInterviewAI(base_path=DATA_PATH)
    ai.load_and_index()
    print("documents:", len(ai.documents))
    print("chunks:", len(ai.chunks))

    print("\n[4] A!SK 질문 생성")
    questions = ai.generate_aisk_questions()
    for i, q in enumerate(questions, 1):
        print(f"\n질문 {i} [{q['question_type']}]")
        print(q['question_text'])
        print("평가포인트:", q['evaluation_points'])
        print("근거자료:", [e['source_title'] for e in q['rag_evidence']])

    print("\nV7 RAG 전체 smoke test 완료")


if __name__ == "__main__":
    main()
