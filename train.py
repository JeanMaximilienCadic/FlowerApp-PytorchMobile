import torch
import numpy as np
from torch import nn, optim
import torch.nn.functional as F
from torchvision import datasets, models, transforms
from torch.utils.data import DataLoader
from collections import OrderedDict
from PIL import Image
from torch import Tensor
import torchvision
import shutil
import argparse
import os
from torchsummary import summary

def validation(model, testloader, criterion, device):
    test_loss = 0
    accuracy = 0
    model.to(device)
    for images, labels in testloader:
        images, labels = images.to(device), labels.to(device)
        # images.resize_(images.shape[0], 3, 224, 224)

        output = model.forward(images)
        test_loss += criterion(output, labels).item()

        ps = torch.exp(output)
        equality = (labels.data == ps.max(dim=1)[1])
        accuracy += equality.type(torch.FloatTensor).mean()
    
    return test_loss, accuracy


def evaluate_model(model, validloader,e ,epochs, running_loss, print_every):
    # Make sure network is in eval mode for inference
    model.eval()

    # Turn off gradients for validation, saves memory and computations
    with torch.no_grad():
        validation_loss, accuracy = validation(model, validloader, criterion, device)

    print("Epoch: {}/{}.. ".format(e + 1, epochs),
          "Training Loss: {:.3f}.. ".format(running_loss / print_every),
          "Validation Loss: {:.3f}.. ".format(validation_loss / len(validloader)),
          "Validation Accuracy: {:.3f}".format((accuracy / len(validloader)) * 100))

    model.train()

    return 0, accuracy



def train(model, trainloader, validloader, epochs, print_every, criterion, optimizer, arch, model_dir="models"):
    epochs = epochs
    print_every = print_every
    steps = 0
    
    # Change to train mode if not already
    model.train()

    best_accuracy = 0
    for e in range(epochs):
        running_loss = 0
        accuracy = None
        for (images, labels) in trainloader:
            steps += 1

            images, labels = images.to(device), labels.to(device)

            optimizer.zero_grad()

            # Forward and backward passes
            outputs = model.forward(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            running_loss += loss.item()

            if steps % print_every == 0:
                running_loss, accuracy = evaluate_model(model, validloader, e, epochs, running_loss, print_every)

        if accuracy is None:
            running_loss, accuracy = evaluate_model(model, validloader, e, epochs, running_loss, print_every)

        is_best = accuracy > best_accuracy
        best_accuracy = max(accuracy, best_accuracy)
        save_checkpoint({
            'epoch': epochs,
            'classifier': model.classifier,
            'state_dict': model.state_dict(),
            'optimizer' : optimizer.state_dict(),
            'class_idx_mapping': model.class_idx_mapping,
            'best_accuracy': (best_accuracy/len(validloader))*100
            }, arch=arch, is_best=is_best, model_dir=model_dir, filename=f'{arch}.ckpt.pth')

def save_checkpoint(state, arch, is_best=False, model_dir="models", filename='checkpoint.pth'):
    torch.save(state, os.path.join(model_dir, filename))
    if is_best:
        shutil.copyfile(os.path.join(model_dir, filename), os.path.join(model_dir,f'{arch}.pth'))

def check_accuracy_on_test(testloader, model):    
    correct = 0
    total = 0
    model.to('cuda')
    with torch.no_grad():
        for data in testloader:
            images, labels = data
            images, labels = images.to('cuda'), labels.to('cuda')
            outputs = model(images)
            _, predicted = torch.max(outputs.data, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()

    return 100 * correct / total


def load_data_folder(data_folder="data", batch_size=64):
    """
    Loads the dataset into a dataloader.

    Arguments:
        data_folder: Path to the folder where data resides. Should have two sub folders named "train" and "valid".

    Returns:
        train_dataloader: Train dataloader iterator.
        valid_dataloader: Validation dataloader iterator.
    """

    train_dir = os.path.join(data_folder, "train")
    valid_dir = os.path.join(data_folder, "valid")
    # Define transforms for the training, validation, and testing sets
    train_transforms = transforms.Compose([
        transforms.RandomRotation(30),
        transforms.RandomResizedCrop(size=224),
        transforms.RandomHorizontalFlip(),
        transforms.RandomVerticalFlip(),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])

    validation_transforms = transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])

    # Load the datasets with ImageFolder
    train_dataset = datasets.ImageFolder(train_dir, transform=train_transforms)
    validation_dataset = datasets.ImageFolder(valid_dir, transform=validation_transforms)

    # Using the image datasets and the transforms, define the dataloaders
    train_dataloader = DataLoader(train_dataset, shuffle=True, batch_size=batch_size, num_workers=4)
    valid_dataloader = DataLoader(validation_dataset, shuffle=True, batch_size=batch_size, num_workers=4)

    return train_dataloader, valid_dataloader, train_dataset.class_to_idx

def replace_head(model):
    for param in model.parameters():
        param.requires_grad = False

    last_child = list(model.children())[-1]
    if type(last_child) == torch.nn.modules.linear.Linear:
        input_features = last_child.in_features
        head = torch.nn.Sequential(OrderedDict([
            ('fc1', nn.Linear(input_features, 4096)),
            ('relu', nn.ReLU()),
            ('dropout', nn.Dropout(p=0.5)),
            ('fc2', nn.Linear(4096, len(class_idx_mapping))),
            ('output', nn.LogSoftmax(dim=1))]))
        model.fc = head
        model.classifier = model.fc
    elif type(last_child) == torch.nn.Sequential:
        input_features = list(last_child.children())[0].in_features
        head = torch.nn.Sequential(OrderedDict([
            ('fc1', nn.Linear(input_features, 4096)),
            ('relu', nn.ReLU()),
            ('dropout', nn.Dropout(p=0.5)),
            ('fc2', nn.Linear(4096, len(class_idx_mapping))),
            ('output', nn.LogSoftmax(dim=1))]))
        model.classifier = head
    return model


def build_model(arch="vgg16", class_idx_mapping=None):
    my_local = dict()
    exec("model = models.{}(pretrained=True)".format(arch), globals(), my_local)

    model = my_local['model']
    model = replace_head(model)
    model.class_idx_mapping = class_idx_mapping
    return model


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir", help="Directory containing the dataset.",
                    default="data", nargs="?")

    ap.add_argument("--learning_rate", help="Learning rate for Adam optimizer. (default: 0.001)",
                    default=0.001, type=float)

    ap.add_argument("--epochs", help="Number of iterations over the whole dataset. (default: 3)",
                    default=100, type=int)

    ap.add_argument("--model_dir", help="Directory which will contain the model checkpoints.",
                    default="models")

    ap.add_argument("--arch", help="Directory which will contain the model checkpoints.",
                    default="densenet161")

    ap.add_argument("--batch_size",
                    default=1, type=int)

    args = vars(ap.parse_args())

    os.system("mkdir -p " + args["model_dir"])

    (train_dataloader, valid_dataloader, class_idx_mapping) = load_data_folder(data_folder=args["data_dir"],
                                                                               batch_size=args["batch_size"])

    device = torch.device("cuda:0")
    model = build_model(arch=args["arch"], class_idx_mapping=class_idx_mapping)
    model.to(device)
    summary(model, input_size=(3, 224, 224))
    criterion = nn.NLLLoss()
    # optimizer = optim.Adam(list(model.children())[-1].parameters(), lr=args["learning_rate"])
    optimizer = optim.Adam(model.classifier.parameters(), lr=args["learning_rate"])
    train(model=model,
          trainloader=train_dataloader,
          validloader=valid_dataloader,
          epochs=args["epochs"],
          print_every=20,
          arch=args["arch"],
          criterion=criterion,
          optimizer=optimizer,
          model_dir=args["model_dir"])
    # model = torchvision.models.resnet18(pretrained=True)
    # model.eval()
    # example = torch.rand(1, 3, 224, 224)
    # traced_script_module = torch.jit.trace(model, example)
    # traced_script_module.save("android/app/src/main/assets/model.pt")
