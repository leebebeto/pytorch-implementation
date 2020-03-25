import torch
from torch import nn
from torch import optim
from torch.utils.data import Dataset, DataLoader
from torch.nn import functional as F
from torchvision import datasets, transforms
from torch.autograd import Variable
from torchvision.utils import save_image
from torchvision.utils import make_grid
import itertools
import numpy as np
import argparse
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from PIL import Image
import os
import cv2
from operator import itemgetter
import matplotlib.pyplot as plt
from PIL import Image
from data import *
from model import *
from utils import *
from PIL import Image
import torch.nn.functional as F
from torch.autograd import Variable
import torch.autograd as autograd


# file revised 	
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# setting args
parser = argparse.ArgumentParser(description = "StarGAN")
parser.add_argument('--batch_size', type = int, default =64, help = "batch_size")
parser.add_argument('--epoch', type = int, default = 150, help = "epoch")
parser.add_argument('--learning_rate_g', type = float, default = 0.0001, help = "learning_rate")
parser.add_argument('--learning_rate_d', type = float, default = 0.0001, help = "learning_rate")
parser.add_argument("--b1", type=float, default=0.5, help="adam: decay of first order momentum of gradient")
parser.add_argument("--b2", type=float, default=0.999, help="adam: decay of first order momentum of gradient")
parser.add_argument("--recon_lambda", type= float, default=10.0, help="recon lambda")
parser.add_argument("--cls_lambda", type= float, default=1.0, help="cls lambda")
parser.add_argument("--gp_lambda", type= float, default=10.0, help="gp lambda")
parser.add_argument("--n_residual_blocks", type=int, default=6, help="number of residual blocks")
parser.add_argument("--n_attribute", type=int, default=5, help="number of attributes")
parser.add_argument("--n_domain", type=int, default=5, help="number of domains")
parser.add_argument("--out_nc", type=int, default=64, help="number of output channels")

args = parser.parse_args()

os.makedirs('result', exist_ok = True)

transforms_ = transforms.Compose([
	transforms.CenterCrop(178),
	transforms.Resize(128),
	transforms.ToTensor(),
	transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
])

#transforms_ = [
#	transforms.CenterCrop(178),
#	transforms.Resize(128),
#	transforms.ToTensor(),
#	transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
#]
#

def weights_init_normal(m):
	classname = m.__class__.__name__
	if classname.find("Conv") != -1:
		torch.nn.init.normal_(m.weight.data, 0.0, 0.02)
	elif classname.find("BatchNorm2d") != -1:
		torch.nn.init.normal_(m.weight.data, 1.0, 0.02)
		torch.nn.init.constant_(m.bias.data, 0.0)


train_data = CelebADataset('dataset/celeba', transforms_ = transforms_, mode = "train")
## test_data = CelebDataset('dataset/celeba', train = False, transform = transforms_)
train_loader = DataLoader(dataset = train_data, batch_size = args.batch_size, shuffle = True)
## test_loader = DataLoader(dataset = test_data, batch_size = args.batch_size, shuffle = True)

print("data loaded")


generator = Generator(args.n_residual_blocks, args.out_nc, args.n_attribute).to(device)
discriminator = Discriminator(args.out_nc, args.n_domain).to(device)

generator.apply(weights_init_normal)
discriminator.apply(weights_init_normal)

optimizer_g = optim.Adam(generator.parameters(), lr = args.learning_rate_g, betas = (args.b1, args.b2))
optimizer_d = optim.Adam(discriminator.parameters(), lr = args.learning_rate_d, betas = (args.b1, args.b2))

criterion_gan = nn.BCELoss()
criterion_recon = nn.L1Loss()


""" Below two functions from https://github.com/eriklindernoren/PyTorch-GAN/blob/master/implementations/stargan/stargan.py   """

def criterion_cls(input, target):
	return F.binary_cross_entropy_with_logits(input, target, size_average=False) / input.size(0)


def compute_gradient_penalty(D, real_samples, fake_samples):
	"""Calculates the gradient penalty loss for WGAN GP"""
	# Random weight term for interpolation between real and fake samples
	Tensor = torch.cuda.FloatTensor
	alpha = Tensor(np.random.random((real_samples.size(0), 1, 1, 1)))
	# Get random interpolation between real and fake samples
	interpolates = (alpha * real_samples + ((1 - alpha) * fake_samples)).requires_grad_(True)
	d_interpolates, _ = D(interpolates)
	fake = Variable(Tensor(np.ones(d_interpolates.shape)), requires_grad=False)
	# Get gradient w.r.t. interpolates
	gradients = autograd.grad(
        outputs=d_interpolates,
        inputs=interpolates,
        grad_outputs=fake,
        create_graph=True,
        retain_graph=True,
        only_inputs=True,
	)[0]
	gradients = gradients.view(gradients.size(0), -1)
	gradient_penalty = ((gradients.norm(2, dim=1) - 1) ** 2).mean()
	return gradient_penalty


generator.train()
discriminator.train()

for epoch in range(args.epoch):
	for i, (image, attr) in enumerate(train_loader):

		image = Variable(image.to(device))
		image = image.float()

		origin_attr = Variable(attr.to(device))

		target_attr = []
		for index in range(args.batch_size):
			target_attr.append([np.random.randint(2) for index in range(origin_attr.shape[1])])
		
		target_attr = torch.tensor(target_attr).to(device)
		target_attr = target_attr.float()	
		if image.shape[0] < args.batch_size: break 


		# update generator
		
		fake = generator(image, target_attr)	


		# update discriminator		
		optimizer_d.zero_grad()

		adv_real, cls_real = discriminator(image)
		adv_fake, cls_fake = discriminator(fake.detach())
		gradient_penalty = compute_gradient_penalty(discriminator, image, fake)

		#loss_d_adv_fake = criterion_gan(adv_fake.detach(), fake(adv_fake))
		#loss_d_adv_real = criterion_gan(adv_real, valid(adv_real))
		#loss_d_adv = 0.5 * (loss_d_adv_fake + loss_d_adv_real)
		loss_d_adv = -torch.mean(adv_real) + torch.mean(adv_fake) + args.gp_lambda * gradient_penalty
		loss_d_cls = criterion_cls(cls_real, origin_attr)
		loss_d  =  loss_d_adv + args.cls_lambda * loss_d_cls


		loss_d.backward()
		optimizer_d.step()
			
		optimizer_g.zero_grad()
		if i % 5 == 0:
			generated_image = generator(image, target_attr)
			recon = generator(generated_image, origin_attr)
			adv_fake, cls_fake = discriminator(generated_image)

			loss_g_recon = criterion_recon(recon, image)
			loss_g_cls = criterion_cls(cls_fake, target_attr)

		# generator_loss
			loss_g_adv = -torch.mean(adv_fake)
#		loss_g_adv = criterion_gan(adv_fake, valid(adv_fake))
		# criterion_gan(adv_fake, valid(adv_fake))

			loss_g = loss_g_adv + args.recon_lambda * loss_g_recon + args.cls_lambda * loss_g_cls

			loss_g.backward()
			optimizer_g.step()
	
		
		total_loss = loss_d + loss_g

		if i % 20 == 0:	
			print('Epoch [{}/{}], Step [{}/{}], Loss:{:.4f}, G-Loss: {:.4f}, G-ADV-Loss:{:.4f}, G-CLS-Loss:{:.4f}, G-Recon-Loss:{:.4f}, D-Loss: {:.4f}, D-ADV-Loss:{:4f}, D-CLS-Loss:{:4f} '.format(epoch+1, args.epoch, i, int(len(train_loader)), total_loss.item(), loss_g.item(), loss_g_adv.item(), loss_g_cls.item(), loss_g_recon.item(), loss_d.item(), loss_d_adv.item(), loss_d_cls.item()))
			with torch.no_grad():
				original = image[0]
				orig_attr = attr[0]
				fake1 = generator(original.unsqueeze(0), torch.FloatTensor([(orig_attr[0] + 1) % 2,0,0,0,0]).unsqueeze(0).to(device))
				fake2 = generator(original.unsqueeze(0), torch.FloatTensor([0,(orig_attr[1] + 1) % 2,0,0,0]).unsqueeze(0).to(device))	
				fake3 = generator(original.unsqueeze(0), torch.FloatTensor([0,0, (orig_attr[2] + 1) % 2,0,0]).unsqueeze(0).to(device))
				fake4 = generator(original.unsqueeze(0), torch.FloatTensor([0,0,0,(orig_attr[3] + 1) % 2,0]).unsqueeze(0).to(device))
				fake5 = generator(original.unsqueeze(0), torch.FloatTensor([0,0,0,0,(orig_attr[4] + 1) % 2]).unsqueeze(0).to(device))
			
	
			result = torch.cat((original, fake1.squeeze(0), fake2.squeeze(0), fake3.squeeze(0), fake4.squeeze(0), fake5.squeeze(0)), 1)
			save_image(result, 'result/%d_%d.png' % (epoch, i), normalize = True)	


			#fake = make_grid(fake[0], nrow = 1, normalize = True)
			#recon = make_grid(recon[0], nrow = 1, normalize = True)
			#image_grid = torch.cat((original, fake, recon), 1)
			#save_image(image_grid, 
			#plot_list = []
			#plot_list.append(image[0])
			#plot_list.append(fake[0])
			#plot_list.append(recon[0])
			#plot_list = torch.stack(plot_list)
			#save_image(result, 'result/%d_%d | ' % (epoch, i) + str(origin_attr[0])[8:26] + '|' + str(target_attr[0])[8:26] + '.png',  normalize = False)





