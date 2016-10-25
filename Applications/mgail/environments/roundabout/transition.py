import tensorflow as tf
import common

class TRANSITION(object):

    def __init__(self, in_dim, out_dim, weights=None):

        self.arch_params = {
            'in_dim': in_dim,
            'out_dim': out_dim,
            'n_hidden_0': 400,
            'n_hidden_1': 500,
            'n_hidden_2': 250,
            'n_hidden_3': 200
        }

        self.solver_params = {
            'lr': 0.001,
            'weight_decay': 0.000001,
            'weights_stddev': 0.08,
        }

        self._init_layers(weights)

    def forward(self, state_, action):

        '''
        :param _input: N_batch x np.concatenate([[x_h, x_ct, x_h_, x_ct_, x_h__, x_ct__], v_t, x_t, a_t, self.is_aggressive, [ct_ind]])
        :param _input: N_batch x action
        :return: prediction: {x_h,x_ct}_t
        '''

        x_H_ = tf.slice(state_, [0, 0], [-1, 6])
        x_ = tf.slice(state_, [0, 0], [-1, 2])
        rest = tf.slice(state_, [0, 6], [-1, -1])

        _input = tf.concat(concat_dim=1, values=[x_H_, action], name='input')

        h0 = tf.nn.xw_plus_b(_input, self.weights['0'], self.biases['0'], name='h0')
        relu0 = tf.nn.relu(h0)

        h1 = tf.nn.xw_plus_b(relu0, self.weights['1'], self.biases['1'], name='h1')
        relu1 = tf.nn.relu(h1)

        # h2 = tf.nn.xw_plus_b(relu1, self.weights['2'], self.biases['2'], name='h2')
        # relu2 = tf.nn.relu(h2)

        # h3 = tf.nn.xw_plus_b(relu2, self.weights['3'], self.biases['3'], name='h3')
        # relu3 = tf.nn.relu(h3)

        delta = tf.nn.xw_plus_b(relu1, self.weights['c'], self.biases['c'], name='delta')

        x = x_ + delta

        x_H = tf.concat(concat_dim=1, values=[x, tf.slice(x_H_, [0, 0], [-1, 4])])

        state = tf.concat(concat_dim=1, values=[x_H, rest], name='state')

        return state

    def backward(self, loss):

        # create an optimizer
        opt = tf.train.AdamOptimizer(learning_rate=self.solver_params['lr'])

        # weight decay
        if self.solver_params['weight_decay']:
            loss += self.solver_params['weight_decay'] * tf.add_n([tf.nn.l2_loss(v) for v in self.trainable_variables])

        # compute the gradients for a list of variables
        self.grads_and_vars = opt.compute_gradients(loss=loss,
                                                    var_list=self.weights.values() + self.biases.values()
                                                    )

        self.grads_and_vars = [(tf.clip_by_value(grad, -1., 1.), var) for grad, var in self.grads_and_vars]

        self.mean_abs_grad, self.mean_abs_w = common.compute_mean_abs_norm(self.grads_and_vars)

        # apply the gradient
        apply_grads = opt.apply_gradients(self.grads_and_vars)

        return apply_grads

    def train(self, state_, action, state):
        state_a = self.forward(state_, action)
        # DEBUG: punish only on last frame transition 6 -> 2
        obs_a = tf.slice(state_a, [0, 0], [-1, 2])
        obs = tf.slice(state, [0, 0], [-1, 2])

        self.loss = tf.nn.l2_loss(obs_a - obs)
        self.minimize = self.backward(self.loss)
        self.acc = self.loss  # stub
        self.state_action_grad = tf.gradients(self.loss, [state_])[0]  # stub

    def _init_layers(self, weights):

        # if a trained model is given
        if weights != None:
            print 'Loading weights... '

        # if no trained model is given
        else:
            weights = {
                '0': tf.Variable(tf.random_normal([self.arch_params['in_dim']    , self.arch_params['n_hidden_0']], stddev=self.solver_params['weights_stddev'])),
                '1': tf.Variable(tf.random_normal([self.arch_params['n_hidden_0'], self.arch_params['n_hidden_1']], stddev=self.solver_params['weights_stddev'])),
                # '2': tf.Variable(tf.random_normal([self.arch_params['n_hidden_1'], self.arch_params['n_hidden_2']], stddev=self.solver_params['weights_stddev'])),
                # '3': tf.Variable(tf.random_normal([self.arch_params['n_hidden_2'], self.arch_params['n_hidden_3']], stddev=self.solver_params['weights_stddev'])),
                'c': tf.Variable(tf.random_normal([self.arch_params['n_hidden_1'], self.arch_params['out_dim']]   , stddev=self.solver_params['weights_stddev'])),
            }

            biases = {
                '0': tf.Variable(tf.random_normal([self.arch_params['n_hidden_0']], stddev=self.solver_params['weights_stddev'])),
                '1': tf.Variable(tf.random_normal([self.arch_params['n_hidden_1']], stddev=self.solver_params['weights_stddev'])),
                # '2': tf.Variable(tf.random_normal([self.arch_params['n_hidden_2']], stddev=self.solver_params['weights_stddev'])),
                # '3': tf.Variable(tf.random_normal([self.arch_params['n_hidden_3']], stddev=self.solver_params['weights_stddev'])),
                'c': tf.Variable(tf.random_normal([self.arch_params['out_dim']], stddev=self.solver_params['weights_stddev']))
            }
        self.weights = weights
        self.biases = biases
        self.trainable_variables = weights.values() + biases.values()