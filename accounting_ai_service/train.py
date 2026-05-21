from datasets import Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments


BASE_MODEL_NAME = "aubmindlab/aragpt2-base"
OUTPUT_DIR = "./models/my_model"

TRAINING_EXAMPLES = [
    {
        "text": "سؤال: ما هي الفاتورة الضريبية؟\nالإجابة: الفاتورة الضريبية هي مستند يوضح بيانات عملية البيع وقيمة ضريبة القيمة المضافة."
    },
    {
        "text": "سؤال: ماذا يحدث للمخزون عند البيع؟\nالإجابة: عند البيع تنخفض كمية المنتج من المخزون بحسب الكمية المباعة."
    },
    {
        "text": "سؤال: ما هو قيد اليومية؟\nالإجابة: قيد اليومية هو تسجيل محاسبي يتكون من طرف مدين وطرف دائن."
    },
    {
        "text": "سؤال: كيف تؤثر المصروفات على الأرباح؟\nالإجابة: المصروفات تقلل صافي الربح لأنها تزيد التكاليف على المنشأة."
    },
    {
        "text": "سؤال: ما معنى الدفع النقدي؟\nالإجابة: الدفع النقدي يعني أن العميل دفع المبلغ مباشرة نقدًا وقت العملية."
    },
    {
        "text": "سؤال: ما معنى البيع الآجل؟\nالإجابة: البيع الآجل يعني بيع البضاعة للعميل مع تأجيل تحصيل المبلغ إلى وقت لاحق."
    },
    {
        "text": "سؤال: ما هي ضريبة القيمة المضافة؟\nالإجابة: ضريبة القيمة المضافة هي ضريبة تضاف على قيمة السلع أو الخدمات حسب النسبة المعتمدة."
    },
    {
        "text": "سؤال: ما فائدة حد التنبيه في المخزون؟\nالإجابة: حد التنبيه يساعد النظام على تنبيه المستخدم عندما تنخفض كمية الصنف عن المستوى المطلوب."
    },
    {
        "text": "سؤال: من أنت؟\nالإجابة: أنا نموذج عبدالرحمن المحاسبي، مساعد ذكاء اصطناعي خاص يساعدك في الأسئلة المحاسبية وإدارة الفواتير والمخزون."
    },
    {
        "text": "سؤال: هل أنت نموذج عام؟\nالإجابة: لا، أنا نموذج محلي مخصص لعبدالرحمن ومهيأ للإجابة عن أسئلة المحاسبة والفواتير والمخزون."
    },
]


def tokenize_examples(tokenizer: AutoTokenizer, dataset: Dataset) -> Dataset:
    def tokenize(example: dict[str, str]) -> dict[str, list[int]]:
        tokens = tokenizer(
            example["text"],
            truncation=True,
            padding="max_length",
            max_length=160,
        )
        tokens["labels"] = tokens["input_ids"].copy()
        return tokens

    return dataset.map(tokenize)


def main() -> None:
    print("تحميل النموذج الأساسي...")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_NAME)
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL_NAME)

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model.config.pad_token_id = tokenizer.pad_token_id

    dataset = Dataset.from_list(TRAINING_EXAMPLES)
    tokenized_dataset = tokenize_examples(tokenizer, dataset)

    training_args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        num_train_epochs=10,
        per_device_train_batch_size=1,
        save_steps=5,
        logging_steps=1,
        report_to="none",
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_dataset,
    )

    print("بدء التدريب...")
    trainer.train()

    print("حفظ النموذج الخاص...")
    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)

    print("تم تدريب النموذج الخاص بنجاح.")


if __name__ == "__main__":
    main()
