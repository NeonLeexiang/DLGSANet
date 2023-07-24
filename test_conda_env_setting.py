import torch

print(torch.cuda.is_available())

print(torch.version)

for i in range(torch.cuda.device_count()):
    print(torch.cuda.get_device_name(i))



