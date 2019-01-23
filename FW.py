

import sys
import tensorflow as tf
import numpy as np
from six.moves import xrange
import time
from utils import get_dist, norm_ball_proj_inner, eps_search, grad_normalization

class FW:
    def __init__(self, sess, model, nb_iter=100, batch_size=1, ord=np.inf, eps=0., clip_min=0, clip_max=1, targeted=True, inception=False, lr = 0.01, loss_type = 'cross_entropy', lambd = 5, beta1 = 0.9, beta2 = 0.99, adaptive = False, output_steps = 10, test = False):

        image_size, num_channels, num_labels = model.image_size, model.num_channels, model.num_labels
        self.sess = sess
        self.nb_iter = nb_iter
        self.model = model
        self.targeted = targeted
        self.batch_size = batch_size
        self.ord = ord
        self.epsilon = eps
        self.clip_min = clip_min
        self.clip_max = clip_max
        self.inception = inception
        self.lr = lr
        self.loss_type = loss_type
        self.lambd = lambd
        self.beta1 = beta1
        self.beta2 = beta2
        self.adaptive = adaptive
        self.output_steps = output_steps
        self.test = test
        
        print ('lambda: ', lambd)

        self.shape = (batch_size,image_size,image_size,num_channels)

        self.img = tf.placeholder(tf.float32, self.shape)
        self.lab = tf.placeholder(tf.float32, (batch_size,num_labels))
        
        def get_loss(eval_points, labels):
            logits, pred = self.model.predict(eval_points)
            if self.loss_type == 'cross_entropy':
                loss = tf.nn.softmax_cross_entropy_with_logits(logits=logits, labels=labels)
            elif self.loss_type == 'cw':
                correct_logit = tf.reduce_sum(labels * logits, axis=1)
                wrong_logit = tf.reduce_max((1-labels) * logits, axis=1)
                loss = tf.maximum(wrong_logit - correct_logit, -50)
            else:
                print ('Unknown Loss Type')
                import sys
                sys.exit()
            eval_adv = tf.equal(pred, tf.argmax(labels, 1))
            return loss, pred, eval_adv
  
        self.loss, self.pred, self.eval_adv = get_loss(self.img, self.lab)
        if not self.targeted:
            self.loss = -self.loss
        self.tloss = tf.reduce_sum(self.loss)
        
        self.gradients, = tf.gradients(self.loss, self.img)
         

    def attack(self, inputs, targets):
        eps = eps_search(self.epsilon, self.ord)
        adv = []
        adv = np.array(inputs)
        time_images = np.zeros((len(inputs)))
        stop_iter = np.zeros((len(inputs)))
        
        index_set = np.arange(0,len(inputs))

        for ep in eps:
            print ('Searching for ep@', ep)
            if(len(index_set) != 0):
                preds = []
                adv_remain = []
                time_remain = []
                stop_iter_remain = []
                
                current_ep = ep*self.lambd

                for i in range(0,len(index_set),self.batch_size):
                    start_time = time.time()
                    start = i
                    end = min(i+self.batch_size, len(inputs))
                    ind = index_set[start:end]
                    if len(ind) < self.batch_size:
                        ind = np.pad(ind, (0, self.batch_size - len(ind)), mode='constant', constant_values=0)
                    
                    batch_data = inputs[ind]
                    batch_lab = targets[ind]

                    x = np.copy(batch_data)

                    last_ls = []
                    max_lr = self.lr
        
                    print ('--------------------')
                    for iteration in range(self.nb_iter):
                        loss, pred, eval_adv, grad = self.sess.run([self.tloss, self.pred, self.eval_adv, self.gradients], {self.img: x, self.lab: batch_lab})
                        

                        
                        grad_normalized = grad_normalization(grad, self.ord)
                        
                        v = - current_ep * grad_normalized + batch_data
                        d = v - x
                        
                        g = np.sum(d* -grad)
 
                        current_lr = max_lr
                           
 
                        x = x + current_lr * d
                            
                        eta = x - batch_data
                        x = batch_data + norm_ball_proj_inner(eta, self.ord, ep)
                    
                        x = np.clip(x, self.clip_min, self.clip_max)
                        
                        
                        if self.test:
                            print (g)
                            if g < 1:
                                break
                        else:
                            if iteration % self.output_steps == 0:
                                dist = get_dist(x, batch_data, self.ord)
                                print ('Iter: ', iteration, 'Loss: ', loss, ' Dist: ', dist , ' Pred: ' , pred, ' Eval: ', eval_adv.all(), ' g: ', g)
                            if eval_adv.all():
                                break

                        
                        last_ls.append(loss)
                        last_ls = last_ls[-5:]
                        if last_ls[-1] > 0.999 * last_ls[0] and len(last_ls) == 5:
                            print (last_ls)
                            print("Early stopping because there is no improvement")
                            break
    
    
                    preds.extend(eval_adv)
                    adv_remain.extend(x)
                    time_remain.extend(np.ones(len(batch_lab))*(time.time() - start_time)/len(batch_lab))
                    stop_iter_remain.append(iteration)
                preds = np.array(preds)
                adv_remain = np.array(adv_remain)
                time_remain = np.array(time_remain)
                stop_iter_remain = np.array(stop_iter_remain)
                succ_ind = [j for j in range(len(index_set)) if preds[j] == True]
                if(self.epsilon == 0.):
                    adv[index_set[succ_ind]] = adv_remain[succ_ind] 
                    time_images[index_set[succ_ind]] = time_remain[succ_ind] 
                    stop_iter[index_set[succ_ind]] = stop_iter_remain[succ_ind] 
                else:
                    adv = adv_remain
                    time_images = time_remain
                    stop_iter = stop_iter_remain
                index_set = np.delete(index_set, succ_ind, 0)
                print('Remaining: ', len(index_set))
                print ('Succ ', len(inputs) - len(index_set), ' / ', len(inputs), ' rate: ', 1 - len(index_set)/ len(inputs)) 
                
#         print (adv[0], stop_iter)
        return adv, time_images, 1 - len(index_set)/ len(inputs), stop_iter