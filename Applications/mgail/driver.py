from mgail import MGAIL
import numpy as np
import tensorflow as tf
import time
import common
import sys


class DRIVER(object):

    def __init__(self, environment):

        self.env = environment
        self.algorithm = MGAIL(environment=self.env)
        self.init_graph = tf.initialize_all_variables()
        self.saver = tf.train.Saver()
        self.test_writer = tf.train.SummaryWriter(self.env.run_dir + '/test')
        self.sess = tf.Session()
        if self.env.trained_model:
            self.saver.restore(self.sess, self.env.trained_model)
        else:
            self.sess.run(self.init_graph)
        self.run_dir = self.env.run_dir
        self.loss = 999. * np.ones(3)
        self.abs_grad = 0 * np.ones(3)
        self.abs_w = 0 * np.ones(3)
        self.reward = 0
        self.reward_std = 0
        self.run_avg = 0.001
        self.discriminator_policy_switch = 0
        self.policy_loop_time = 0
        self.disc_acc = 0
        self.er_count = 0
        self.itr = 0
        self.best_reward = 0
        np.set_printoptions(precision=2)
        np.set_printoptions(linewidth=160)

    def run_tensorflow(self, fetches, feed_dict, ind, update_stats=True):
        run_vals = self.sess.run(fetches=fetches, feed_dict=feed_dict)
        if update_stats:
            self.loss[ind] = self.run_avg * self.loss[ind] + (1-self.run_avg) * np.asarray(run_vals[1])
            self.abs_grad[ind] = self.run_avg * self.abs_grad[ind] + (1-self.run_avg) * np.asarray(run_vals[2])
            self.abs_w[ind] = self.run_avg * self.abs_w[ind] + (1-self.run_avg) * np.asarray(run_vals[3])
        return run_vals

    def train_autoencoder(self):
        alg = self.algorithm
        if self.itr < self.env.model_identification_time:
            er = self.algorithm.er_expert
        else:
            er = self.algorithm.er_agent
        states = []
        for i in range(int(self.env.sae_batch/self.env.batch_size)):
            state_, action, _, _, _ = er.sample()
            state_ = np.squeeze(np.copy(state_), axis=1)
            states.append(state_)
        states = np.reshape(np.array(states), (1, -1, self.env.state_size))
        fetches = [alg.sparse_ae.minimize, alg.sparse_ae.loss,
                   alg.sparse_ae.mean_abs_grad, alg.sparse_ae.mean_abs_w]
        feed_dict = {alg.states: states}
        self.run_tensorflow(fetches, feed_dict, ind=3)

    def train_transition(self):
        alg = self.algorithm
        for k_t in range(self.env.K_T):
            if self.itr < self.env.model_identification_time:
                er = self.algorithm.er_expert
            else:
                er = self.algorithm.er_agent
            trans_iters = self.num_transition_iters()
            state_, action = er.sample_trajectory(trans_iters)
            states = np.transpose(state_, axes=[1, 0, 2])
            actions = np.transpose(action, axes=[1, 0, 2])
            fetches = [alg.transition.minimize, alg.transition.loss,
                       alg.transition.mean_abs_grad, alg.transition.mean_abs_w, alg.transition.loss_summary]
            feed_dict = {alg.states: states, alg.actions: actions}
            run_vals = self.run_tensorflow(fetches, feed_dict, ind=0)
            self.test_writer.add_summary(run_vals[4], self.itr)

    def train_discriminator(self):
        alg = self.algorithm
        for k_d in range(self.env.K_D):
            state_a_, action_a, _, state_a, terminals = self.algorithm.er_agent.sample()
            state_e_, action_e, _, state_e, _ = self.algorithm.er_expert.sample()
            state_a_ = np.squeeze(state_a_, axis=1)
            state_e_ = np.squeeze(state_e_, axis=1)
            states = np.concatenate([state_a_, state_e_])
            actions = np.concatenate([action_a, action_e])
            # labels (policy/expert) : 0/1, and in 1-hot form: policy-[1,0], expert-[0,1]
            labels_a = np.zeros(shape=(alg.er_agent.batch_size,))
            labels_e = np.ones(shape=(alg.er_agent.batch_size,))
            labels = np.expand_dims(np.concatenate([labels_a, labels_e]), axis=1)
            fetches = [alg.discriminator.minimize, alg.discriminator.loss, alg.discriminator.mean_abs_grad,
                       alg.discriminator.mean_abs_w, alg.discriminator.acc, alg.discriminator.loss_summary,
                       alg.discriminator.acc_summary]
            feed_dict = {alg.states: np.array([states]), alg.actions: np.array([actions]), alg.label: labels}
            run_vals = self.run_tensorflow(fetches, feed_dict, ind=1)
            self.disc_acc = self.run_avg * self.disc_acc + (1 - self.run_avg) * np.asarray(run_vals[4])
            self.test_writer.add_summary(run_vals[5], self.itr)
            self.test_writer.add_summary(run_vals[6], self.itr)

    def train_policy(self):
        alg = self.algorithm
        for k_p in range(self.env.K_P):
            if self.itr < self.env.model_identification_time:
                state_e_, action_e, _, state_e, _ = self.algorithm.er_expert.sample()
                state_e_ = np.squeeze(state_e_, axis=1)
                fetches = [alg.policy.minimize_sl, alg.policy.loss_sl, alg.policy.mean_abs_grad_sl,
                           alg.policy.mean_abs_w_al, alg.policy.loss_sl_summary]
                feed_dict = {alg.states: np.array([state_e_]), alg.actions: np.array([action_e])}
                run_vals = self.run_tensorflow(fetches, feed_dict, ind=2, update_stats=True)
                self.test_writer.add_summary(run_vals[4], self.itr)

            if self.itr > self.env.model_identification_time:
                if self.env.get_status():
                    state = self.env.reset()
                else:
                    state = self.env.get_state()
                fetches = [alg.policy.minimize_al, alg.policy.loss_al, alg.policy.mean_abs_grad_al,
                           alg.policy.mean_abs_w_al, alg.policy.loop_time, alg.policy.loss_al_summary]
                feed_dict = {alg.states: np.array([[state]]), alg.gamma: self.env.gamma}
                run_vals = self.run_tensorflow(fetches, feed_dict, ind=2)
                self.policy_loop_time = self.run_avg * self.policy_loop_time + (1 - self.run_avg) * np.asarray(run_vals[4])
                self.test_writer.add_summary(run_vals[5], self.itr)

    def collect_experience(self, record=1, vis=0, n_steps=None, noise_flag=True):
        alg = self.algorithm
        observation = self.env.reset()
        observation_ = observation
        t = 0
        R = 0
        done = 0
        if n_steps is None:
            n_steps = self.env.n_steps_test

        while not done:
            noise = np.random.normal(scale=self.env.sigma, size=self.env.action_space.shape[0])
            if vis:
                self.env.render()

            if not noise_flag:
                noise *= 0

            a = self.sess.run(fetches=[alg.action_test], feed_dict={alg.states: np.reshape(observation, [1, 1, -1])})
            a_n = np.squeeze(a) + noise

            observation, reward, done, info = self.env.step(a_n, mode='python')

            # d_obs = np.sum(abs(observation_ - observation))
            # observation_ = observation
            # print d_obs

            done = done or t > n_steps

            t += 1

            R += reward

            if record:
                self.algorithm.er_agent.add(actions=[a_n], rewards=[reward], next_states=[observation], terminals=[done])

        return R

    def reset_module(self, module):

        temp = set(tf.all_variables())

        module.backward(module.loss)

        self.sess.run(tf.initialize_variables(set(tf.all_variables()) - temp))

    def train_step(self):
        # phase_0: Model identification:
        # autoencoder: learning from expert data
        # transition: learning from the expert data
        # discriminator: learning concurrently with policy
        # policy: learning in SL mode

        # phase_1: Adversarial training
        # autoencoder: learning from agent data
        # transition: learning from agent data
        # discriminator: learning in an interleaved mode with policy
        # policy: learning in adversarial mode

        if self.itr % self.env.reset_itrvl == 0:
            # reset transition module
            self.reset_module(self.algorithm.transition)
            for i in range(self.env.n_reset_iters):
                self.train_transition()

        if self.itr % self.env.collect_experience_interval == 0:
            self.collect_experience()

        if self.env.use_sae and self.env.train_flags[0]:
            self.train_autoencoder()

        if self.env.train_flags[1]:
            self.train_transition()

        if self.env.train_flags[2]:
            if self.discriminator_policy_switch:
                self.train_discriminator()
            else:
                self.train_policy()

        # print progress
        if self.itr % 100 == 0:
            self.print_info_line('slim')

        # switch discriminator-policy
        if self.itr % self.env.discr_policy_itrvl == 0:
            self.discriminator_policy_switch = not self.discriminator_policy_switch

    def num_transition_iters(self):
        if self.loss[0] > self.env.trans_loss_th:
            trans_iters = 2
        else:
            trans_iters = int((2.-self.env.max_trans_iters)/self.env.trans_loss_th * self.loss[0] + self.env.max_trans_iters)
        return trans_iters

    def print_info_line(self, mode):
        if mode == 'full':
            buf = '%s Training: iter %d, loss: %s, disc_acc: %f, grads: %s, weights: %s, er_count: %d, R: %.1f, R_std: %.2f\n' % \
                  (time.strftime("%H:%M:%S"), self.itr, self.loss, self.disc_acc, self.abs_grad, self.abs_w,
                   self.algorithm.er_agent.count, self.reward, self.reward_std)
            if hasattr(self.env, 'log_fid'):
                self.env.log_fid.write(buf)
        else:
            buf = "processing iter: %d, loss(transition,discriminator,policy): %s, disc_acc: %f" % (self.itr, self.loss, self.disc_acc)
        sys.stdout.write('\r' + buf)

    def save_model(self, dir_name=None):
        if dir_name is None:
            dir_name = self.run_dir + '/snapshots/'
        fname= dir_name + time.strftime("%Y-%m-%d-%H-%M-") + ('%0.6d.sn' % self.itr)
        common.save_params(fname=fname, saver=self.saver, session=self.sess)
