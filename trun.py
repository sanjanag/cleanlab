from cleanlab import Datalab
from datasets import load_dataset

if __name__ == "__main__":
    dataset = load_dataset("cifar10", split="test")
    print(dataset)
    datalab = Datalab(data=dataset[:10], label_name="label", image_key="img")
    datalab.find_issues()
    datalab.report()
