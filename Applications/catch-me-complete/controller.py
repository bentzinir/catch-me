import math
import theano as t
import theano.tensor as tt
import numpy as np
import common
import optimizers
from simulator import step
from gru_layer import GRU_LAYER
from conv_pool import CONV_POOL
from theano.tensor.shared_randomstreams import RandomStreams
from theano.ifelse import ifelse

class CONTROLLER(object):

    def __init__(self,
                 x_host_0,
                 v_host_0,
                 x_target_0,
                 v_target_0,
                 x_mines_0,
                 mines_map,
                 time_steps,
                 force,
                 n_steps_0,
                 n_steps_1,
                 lr,
                 goal_1,
                 trnsprnt,
                 rand_goals,
                 game_params,
                 arch_params,
                 solver_params,
                 params):

        self._connect(game_params, solver_params)

        self._init_layers(params, arch_params)

        def _line_segment_point_dist(v, w, p): # x3,y3 is the point
            px = w[0] - v[0]
            py = w[1] - v[1]

            something = px*px + py*py

            # something = tt.printing.Print('someting')(something)
            u =  ((p[:,0] - v[0]) * px + (p[:,1] - v[1]) * py) / (something + 1e-4)

            # if u > 1:
            #     u = 1
            # elif u < 0:
            #     u = 0

            u = tt.nnet.relu(u) - tt.nnet.relu(u-1)

            x = v[0] + u * px
            y = v[1] + u * py

            dx = x - p[:,0]
            dy = y - p[:,1]

            # Note: If the actual distance does not matter,
            # if you only want to compare what this function
            # returns to other results of this function, you
            # can just return the squared distance instead
            # (i.e. remove the sqrt) to gain a little performance

            dist = dx*dx + dy*dy

            return dist

        def _pdist(X,Y):
            translation_vectors = X.reshape((X.shape[0], 1, -1)) - Y.reshape((1, Y.shape[0], -1))
            dist = (tt.abs_(translation_vectors)).sum(2)
            return dist

        def _step_state(x_host_, v_host_, x_target_, v_target_, u_ext, u):

            x_target_e, v_target_e= step(x_target_, v_target_)

            # 1. approximated dynamic of the next state
            # 1.1 target (moves in fixed speed)
            v_target_a = v_target_
            x_target_a = x_target_ + self.dt * v_target_a

            # 2. difference in predictions
            # 2.1 target
            n_v_t = v_target_e - v_target_a
            n_x_t = x_target_e - x_target_a

            # 3. disconnect the gradient of the noise signals
            # 3.1 target
            n_v_t = common.disconnected_grad(n_v_t)
            n_x_t = common.disconnected_grad(n_x_t)

            # 4. add the noise to the approximation
            # 4.1 target
            v_target = v_target_a + n_v_t
            x_target = x_target_a + n_x_t

            # 5. step host
            a = (u + u_ext)*self.inv_m
            v_host_e = v_host_ + a * self.dt
            x_host_e = x_host_ + v_host_e * self.dt
            x_host, v_host = common.bounce(x_host_e, v_host_e, self.w)


            return x_host, v_host, x_target, v_target

        def _recurrence_0(time_step, f, x_host_, v_host_, x_target_, v_target_, h_0_, goal_0):
            '''
            controller 0 is responsible for navigating from current host position x_host_ to goal_0
            while neutralizing the external force

            state:
             1. dist (2): vector from current position to goal_0
             2. x (2): current position
             3. v (2): current velocity
            '''

            dist = goal_0 - x_host_

            host_2_walls = tt.concatenate([x_host_, self.w - x_host_])

            state = tt.concatenate([dist, host_2_walls, v_host_])

            h_0 = self.params[0]['gru_layer'].step(state, h_0_)

            u = tt.dot(h_0, self.params[0]['W_c']) + self.params[0]['b_c']

            x_host, v_host, x_target, v_target = _step_state(x_host_, v_host_, x_target_, v_target_, f, u)

            # cost:
            discount_factor = 0.99**time_step

            # 0. smooth acceleration policy
            cost_accel = discount_factor * tt.mean(u**2)
            # cost_accel = discount_factor * tt.mean(tt.abs_(u))

            # 1. forcing host to move towards goal_0
            dist_from_goal = tt.mean((goal_0 - x_host)**2)
            # dist_from_goal = tt.mean(tt.abs_(goal_0 - x_host))

            cost_progress = discount_factor * dist_from_goal

            return (x_host, v_host, x_target, v_target, h_0, cost_accel, cost_progress)#, t.scan_module.until(dist_from_goal < 0.25)

        def controler_0_dummy(x_host_0, v_host_0, x_target_0, v_target_0, goal):

            x1 = 0.9 * x_host_0 + 0.1 * goal
            x2 = 0.8 * x_host_0 + 0.2 * goal
            x3 = 0.7 * x_host_0 + 0.3 * goal
            x4 = 0.6 * x_host_0 + 0.4 * goal
            x5 = 0.5 * x_host_0 + 0.5 * goal
            x6 = 0.4 * x_host_0 + 0.6 * goal
            x7 = 0.3 * x_host_0 + 0.7 * goal
            x8 = 0.2 * x_host_0 + 0.8 * goal
            x9 = 0.1 * x_host_0 + 0.9 * goal

            c_0_host_traj = tt.stack([x1,x2,x3,x4,x5,x6,x7,x8,x9])
            c_0_host_v = tt.stack([v_host_0, v_host_0])
            c_0_target_traj = tt.stack([x_target_0,
                                              x_target_0,
                                              x_target_0,
                                              x_target_0,
                                              x_target_0,
                                              x_target_0,
                                              x_target_0,
                                              x_target_0,
                                              x_target_0
                                              ])
            c_0_target_v = tt.stack([v_target_0, v_target_0])

            c_0_cost_accel = 0 * tt.mean(x_host_0)
            c_0_cost_progress = 0 * tt.mean(x_host_0)

            return c_0_host_traj, c_0_host_v, c_0_target_traj, c_0_target_v, c_0_cost_accel, c_0_cost_progress

        def _recurrence_1(rand_goal, x_host_, v_host_, x_target_, v_target_, time_steps, force, x_mines, mines_map, goal_1, trnsprnt):
            '''
            controller 1 is responsible for navigating from current host position x_host_ to goal_1 while dodging mines

            state:
             1. dist (2): vector from current position to goal_1
             2. x (2): current position
             3. x_mines (2): mines locations
            '''

            host_2_goal = goal_1 - x_host_

            host_2_mines = x_mines - x_host_

            host_2_walls = tt.concatenate([x_host_, self.w - x_host_])

            d_host_mines = (tt.abs_(host_2_mines)).sum(axis=1)

            state = tt.concatenate([host_2_goal, host_2_walls, tt.flatten(host_2_mines), tt.flatten(d_host_mines)])

            goal_map = tt.zeros_like(mines_map)
            host_map = tt.zeros_like(mines_map)

            goal_1_round = tt.cast(tt.clip(goal_1,0.1,self.w-1.1),'int32')
            x_host_round = tt.cast(tt.clip(x_host_,0.1,self.w-1.1),'int32')

            goal_map = tt.set_subtensor(goal_map[goal_1_round[0],goal_1_round[1]],1)
            host_map = tt.set_subtensor(host_map[x_host_round[0],x_host_round[1]],1)

            state = tt.stack([mines_map,goal_map,host_map],axis=2)
            # state = tt.stack([mines_map,mines_map,mines_map],axis=2)

            state = state.dimshuffle('x',2,0,1)

            h_0 = self.params[1]['conv_0'].step(state)

            h_1 = self.params[1]['conv_1'].step(h_0)

            # h_2 = self.params[1]['conv_2'].step(h_1)

            h_2 = tt.flatten(h_1)

            h_3 = tt.dot(h_2, self.params[1]['W_3']) + self.params[1]['b_3']

            relu_3 = tt.nnet.relu(h_3)

            u = tt.dot(relu_3, self.params[1]['W_c']) + self.params[1]['b_c']

            goal_0 = u + x_host_

            goal_0 = tt.clip(goal_0, 0, self.w)

            goal_0 = ifelse(tt.eq(trnsprnt,1), rand_goal, goal_0)

            # [c_0_host_traj, c_0_host_v, c_0_target_traj, c_0_target_v, c_0_h, c_0_cost_accel, c_0_cost_progress], scan_updates = t.scan(fn=_recurrence_0,
            #                                         sequences=[time_steps, force],
            #                                         outputs_info=[x_host_, v_host_, x_target_, v_target_, self.params[0]['h_0'], None, None],
            #                                         non_sequences=[goal_0],
            #                                         n_steps=n_steps_0,
            #                                         name='scan_func')

            c_0_host_traj, c_0_host_v, c_0_target_traj, c_0_target_v, c_0_cost_accel, c_0_cost_progress = controler_0_dummy(x_host_, v_host_, x_target_, v_target_, goal_0)

            x_host = c_0_host_traj[-1]
            v_host = c_0_host_v[-1]
            x_target = c_0_target_traj[-1]
            v_target = c_0_target_v[-1]

            # costs
            # 1. forcing host to move towards goal_1
            # dist_from_goal = tt.mean((goal_1 - x_host)**2)
            dist_from_goal = tt.mean(tt.abs_(goal_1 - x_host))
            c_1_cost_progress = dist_from_goal

            # 2. dodge mines
            d_host_mines = _pdist(c_0_host_traj, x_mines)
            # d_host_mines = _line_segment_point_dist(x_host, x_host_, x_mines)
            # c_1_cost_mines = tt.sum(tt.nnet.relu(self.d_mines - d_host_mines))
            c_1_cost_mines = tt.mean(tt.exp(-0.5*d_host_mines))
            # c_1_cost_mines = tt.exp(-5*d_host_mines)

            # 3. make small steps
            # c1_cost_step_size = tt.mean(tt.abs_(u))
            c1_cost_step_size = tt.mean(u**2)

            return (x_host, v_host, x_target, v_target,
                    c_0_host_traj, c_0_target_traj, goal_0,
                    c_1_cost_mines, c_1_cost_progress, c1_cost_step_size, c_0_cost_accel, c_0_cost_progress, d_host_mines), t.scan_module.until(dist_from_goal < 0.1)

        [c_1_host_traj, c_1_host_v, c_1_target_traj, c_1_target_v,
         c_0_host_traj, c_0_target_traj, goals_0,
         c_1_cost_mines, c_1_cost_progress, c1_cost_step_size, c_0_costs_accel, c_0_costs_progress, d_host_mines], scan_updates = t.scan(fn=_recurrence_1,
                                                sequences=[rand_goals],
                                                outputs_info=[x_host_0, v_host_0, x_target_0, v_target_0,\
                                                              None, None, None, None, None, None, None, None, None],
                                                non_sequences=[time_steps, force, x_mines_0, mines_map, goal_1, trnsprnt],
                                                n_steps=n_steps_1,
                                                name='scan_func')

        self.c_0_cost_accel = tt.mean(c_0_costs_accel)
        self.c_0_cost_progress = tt.mean(c_0_costs_progress)

        self.c_1_cost_progress = tt.mean(c_1_cost_progress)
        self.c_1_cost_mines = tt.mean(c_1_cost_mines)
        self.c_1_cost_step_size = tt.mean(c1_cost_step_size)

        self.weighted_cost = []
        self.weighted_cost.append(
                    self.c_0_w_accel * self.c_0_cost_accel
                    + self.c_0_w_progress * self.c_0_cost_progress
        )

        self.weighted_cost.append(
                    self.c_1_w_progress * self.c_1_cost_progress
                    + self.c_1_w_mines * self.c_1_cost_mines
                    + self.c_1_w_step_size * self.c_1_cost_step_size
        )

        self.cost = []
        self.cost.append(
            self.c_0_cost_accel
            + self.c_0_cost_progress
        )

        self.cost.append(
            self.c_1_cost_progress
            + self.c_1_cost_mines
        )

        gradients = []
        gradients.append(common.create_grad_from_obj(objective=self.weighted_cost[0], params=self.param_struct[0].params, decay_val=solver_params['controler_0']['l1_weight_decay'], grad_clip_val=solver_params['controler_0']['grad_clip_val']))
        gradients.append(common.create_grad_from_obj(objective=self.weighted_cost[1], params=self.param_struct[1].params, decay_val=solver_params['controler_1']['l1_weight_decay'], grad_clip_val=solver_params['controler_1']['grad_clip_val']))

        gradients[0] = [tt.clip(g,-solver_params['controler_0']['grad_clip_val'],solver_params['controler_0']['grad_clip_val']) for g in gradients[0]]
        gradients[1] = [tt.clip(g,-solver_params['controler_1']['grad_clip_val'],solver_params['controler_1']['grad_clip_val']) for g in gradients[1]]

        self.updates = []
        self.updates.append(optimizers.optimizer(lr=lr, param_struct=self.param_struct[0], gradients=gradients[0], solver_params=solver_params['controler_0']))
        self.updates.append(optimizers.optimizer(lr=lr, param_struct=self.param_struct[1], gradients=gradients[1], solver_params=solver_params['controler_1']))

        self.x_h = c_0_host_traj
        self.x_t = c_0_target_traj
        self.x_mines = x_mines_0
        self.goal_0 = goals_0
        self.goal_1 = goal_1
        self.d_host_mines = d_host_mines

        self.grad_mean = []
        self.grad_mean.append(common.calculate_mean_abs_norm(gradients[0]))
        self.grad_mean.append(common.calculate_mean_abs_norm(gradients[1]))

        self.params_abs_norm = []
        self.params_abs_norm.append(common.calculate_mean_abs_norm(self.param_struct[0].params))
        self.params_abs_norm.append(common.calculate_mean_abs_norm(self.param_struct[1].params))

    def _connect(self, game_params, solver_params):

        self.dt = game_params['dt']
        self.w = game_params['width']
        self.inv_m = np.float32(1./game_params['m'])
        self.v_max = game_params['v_max']
        self.c_0_w_accel = solver_params['controler_0']['w_accel']
        self.c_0_w_progress = solver_params['controler_0']['w_progress']
        self.c_1_w_progress = solver_params['controler_1']['w_progress']
        self.c_1_w_mines = solver_params['controler_1']['w_mines']
        self.c_1_w_step_size = solver_params['controler_1']['w_step_size']
        self.d_mines = game_params['d_mines']
        self.n_mines = game_params['n_mines']
        self.v_max = game_params['v_max']
        self.switch_interval = solver_params['switch_interval']
        self.srng = RandomStreams()

    def _init_layers(self, params, arch_params):

        self.params = []

        # if a trained model is given
        if params[0] != None:
            pass
            # self.gru_layer_0 = GRU_LAYER(params=params[0], name='0')
            # self.W_c_0 = t.shared(params['W_0_c'], name='W_c_0', borrow=True)
            # self.b_c_0 = t.shared(params['b_0_c'], name='b_c_0', borrow=True)
        else:
            self.params.append(
                {
                'gru_layer': GRU_LAYER(init_mean=0,
                                       init_var=0.1,
                                       nX=8,
                                       nH=arch_params['controler_0']['n_hidden_0'],
                                       name='gru0'),

                'h_0': np.zeros(shape=arch_params['controler_0']['n_hidden_0'], dtype=t.config.floatX),

                'W_c': common.create_weight(input_n=arch_params['controler_0']['n_hidden_0'],
                                            output_n=2,
                                            suffix='0'),

                'b_c': common.create_bias(output_n=2,
                                          value=0.1,
                                          suffix='0')
                }
            )

        if params[1] != None:
            pass
            # self.gru_layer_1 = GRU_LAYER(params=params[1], name='1')
            # self.W_c_1 = t.shared(params['W_c_1'], name='W_c_1', borrow=True)
            # self.b_c_1 = t.shared(params['b_c_1'], name='b_c_1', borrow=True)
        else:
            self.params.append(
                {

                'conv_0': CONV_POOL(filter_shape=(4,3,3,3),#(number of filters, num input feature maps,filter height, filter width)
                                    image_shape=(1,3,self.w,self.w),#(batch size, num input feature maps,image height, image width)
                                    border_mode='valid',
                                    poolsize=(2,2),
                                    ),
                'conv_1': CONV_POOL(filter_shape=(4,4,1,1),#(number of filters, num input feature maps,filter height, filter width)
                                    image_shape=(1,4,4,4),#(batch size, num input feature maps,image height, image width)
                                    border_mode='valid',
                                    poolsize=(1,1),
                                    ),
                # 'conv_2': CONV_POOL(filter_shape=(4,1,3,3),#(number of filters, num input feature maps,filter height, filter width)
                #                     image_shape=(1,1,29,29),#(batch size, num input feature maps,image height, image width)
                #                     border_mode='valid',
                #                     poolsize=(2,2),
                #                     ),

                'W_3': common.create_weight(input_n=64,#6+3*self.n_mines,#arch_params['controler_1']['n_hidden_0'],
                                            output_n=arch_params['controler_1']['n_hidden_1'],
                                            suffix='0'),

                'b_3': common.create_bias(output_n=arch_params['controler_1']['n_hidden_1'],
                                          value=0.1,
                                          suffix='0'),

                'W_c': common.create_weight(input_n=arch_params['controler_1']['n_hidden_1'],
                                            output_n=2,
                                            suffix='1'),

                'b_c': common.create_bias(output_n=2,
                                          value=0.1,
                                          suffix='0')
                }
            )

        self.param_struct = []
        self.param_struct.append(common.PARAMS(self.params[0]['W_c'],
                                               self.params[0]['b_c'],
                                               *self.params[0]['gru_layer'].params
                                               ))

        self.param_struct.append(common.PARAMS(
                                               # self.params[1]['W_0'],
                                               # self.params[1]['b_0'],
                                               self.params[1]['W_3'],
                                               self.params[1]['b_3'],
                                               self.params[1]['W_c'],
                                               self.params[1]['b_c'],
                                               self.params[1]['conv_0'].params[0],# W
                                               self.params[1]['conv_0'].params[1],# b
                                               self.params[1]['conv_1'].params[0],# W
                                               self.params[1]['conv_1'].params[1],# b
                                               # self.params[1]['conv_2'].params[0],# W
                                               # self.params[1]['conv_2'].params[1],# b
                                               ))