import tensorflow as tf 
import numpy as np 
import matplotlib.pyplot as plt 
import itertools
import time
import util

class NeuralTransmitter():
    def __init__(self, 
                 preamble,
                 groundtruth = util.qpsk,
                 n_bits = 2,
                 n_hidden = [32, 20],
                 stepsize = 1e-2,
                 lambda_p = 0.1,
                 initial_logstd = -2.
                 ):

        # Network variables
        self.preamble = preamble
        self.lambda_p = lambda_p
        self.n_bits = n_bits
        self.groundtruth = groundtruth

        # Create image directories
        self.im_dir = 'figures/'+str(np.random.randint(1,1000))+'_'+str(self.n_bits)+'/'
        util.create_dir(self.im_dir)
        self.im_dir += '%04d.png'
        print("im_dir:",self.im_dir)

        # Placeholders for training
        self.input = tf.placeholder(tf.float32, [None, self.n_bits]) # -1 or 1
        self.actions_re = tf.placeholder(tf.float32, [None]) 
        self.actions_im = tf.placeholder(tf.float32, [None])
        self.adv = tf.placeholder(tf.float32, [None]) # advantages for gradient computation
        # self.stepsize = tf.placeholder(tf.float32, []) # stepsize
    
        # Network definiton
        layers = [self.input]
        for num in n_hidden:
            h = tf.contrib.layers.fully_connected(
                inputs = layers[-1],
                num_outputs = num,
                activation_fn = tf.nn.relu, # relu activation for hidden layer
                weights_initializer = util.normc_initializer(1.0),
                biases_initializer = tf.constant_initializer(.1)
            )
            layers.append(h)

        self.re_mean = tf.contrib.layers.fully_connected(
                inputs = layers[-1],
                num_outputs = 1,
                activation_fn = None,
                weights_initializer = util.normc_initializer(.2),
                biases_initializer = tf.constant_initializer(0.0)
        )

        self.im_mean = tf.contrib.layers.fully_connected(
                inputs = layers[-1],
                num_outputs = 1,
                activation_fn = None,
                weights_initializer = util.normc_initializer(.2),
                biases_initializer = tf.constant_initializer(0.0)
        )

        self.re_logstd = tf.Variable(initial_logstd)
        self.im_logstd = tf.Variable(initial_logstd)
        self.re_std = tf.exp(self.re_logstd)
        self.im_std = tf.exp(self.im_logstd)

        # randomized actions
        self.re_distr = tf.contrib.distributions.Normal(self.re_mean, self.re_std)
        self.im_distr = tf.contrib.distributions.Normal(self.im_mean, self.im_std)

        self.re_sample = self.re_distr.sample()
        self.im_sample = self.im_distr.sample()

        # Compute log-probabilities for gradient estimation
        self.re_logprob = self.re_distr.log_prob(self.actions_re)
        self.im_logprob = self.im_distr.log_prob(self.actions_im)

        self.surr = - tf.reduce_mean(self.adv * (self.re_logprob + self.im_logprob))
        self.optimizer = tf.train.AdamOptimizer(stepsize)
        self.update_op = self.optimizer.minimize(self.surr)

        self.sess = tf.Session()
        self.sess.run(tf.global_variables_initializer())


    def policy_update(self, signal_b_g_g):
        adv = - self.lasso_loss(signal_b_g_g)
        print(signal_b_g_g.shape)
        print("avg reward:",np.average(adv))

        _ = self.sess.run([self.update_op], feed_dict={
                self.input: self.input_accum,
                self.actions_re: self.actions_re_accum,
                self.actions_im: self.actions_im_accum,
                self.adv: adv
        })


    def transmit(self, signal_b, save=True):

        re, im = self.sess.run([self.re_sample, self.im_sample], feed_dict={
                self.input: signal_b
            })

        if save:
            self.input_accum = signal_b
            self.actions_re_accum = np.squeeze(re)
            self.actions_im_accum = np.squeeze(im)

        signal_m = np.array([np.squeeze(re),np.squeeze(im)]).T
        return signal_m 


    def evaluate(self, signal_b):
        # run policy
        return np.squeeze(self.sess.run(self.action_means, feed_dict={
                self.input: signal_b
            }))   


    def visualize(self, iteration):
        start_time = time.time()
        """
        Plots a constellation diagram. (https://en.wikipedia.org/wiki/Constellation_diagram)
        """
        bitstrings = list(itertools.product([-1, 1], repeat=self.n_bits))
        
        fig = plt.figure(figsize=(8, 8))
        plt.title('Constellation Diagram', fontsize=20)
        ax = fig.add_subplot(111)
        ax.set(ylabel='imaginary part', xlabel='real part')

        for bs in bitstrings:
            x,y = self.evaluate(np.array(bs)[None])
            label = (np.array(bs)+1)/2
            ax.scatter(x, y, label=str(label), color='purple', marker="d")
            ax.annotate(str(label), (x, y), size=10)
        ax.axvline(0, color='grey')
        ax.axhline(0, color='grey')
        #ax.grid()
    
        if self.groundtruth:
            for k in self.groundtruth.keys():
                re_gt, im_gt = self.groundtruth[k]
                ax.scatter(re_gt, im_gt, s=5, color='purple')
                # ax.annotate(''.join([str(b) for b in k]), (re_gt, im_gt), size=5)
        
        
        # plot modulated preamble
        mod_preamble = self.transmit(self.preamble, False)
        ax.scatter(mod_preamble[:,0], mod_preamble[:,1], alpha=0.1, color="red")

        plt.xlim([-3, 3])
        plt.ylim([-3, 3])
        plt.savefig(self.im_dir % iteration)
        plt.close()


    def lasso_loss(self, signal_b_g_g):
        return np.linalg.norm(self.input_accum - signal_b_g_g, ord=1, axis=1) + \
                    self.lambda_p*(self.actions_re**2 + self.actions_im**2)