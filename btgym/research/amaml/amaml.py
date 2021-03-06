
import numpy as np
import tensorflow as tf

from btgym.algorithms import BaseAAC


class MetaA3C_0_0(BaseAAC):
    """
    Develop:
        Meta-learning A3C to be.

        Stage 1: straightforward implementation .
    """
    def __init__(self, cycles_per_trial=1, **kwargs):
        """

        Args:
            cycles_per_trial (int):         outer loop
            kwargs:                         BaseAAC kwargs
        """
        try:
            super(MetaA3C_0_0, self).__init__(_log_name='MetaA3C_0.0', _use_target_policy=True, **kwargs)
            self.current_trial_num = -1
            self.cycles_per_trial = cycles_per_trial
            self.cycles_counter = 1
            with tf.device(self.worker_device):
                with tf.name_scope('local'):
                    # Make local optimizer:
                    # TODO: here should be beta step-size:
                    self.meta_optimizer = tf.train.AdamOptimizer(self.learn_rate_decayed, epsilon=1e-5)
                    self.meta_train_op = self.meta_optimizer.apply_gradients(
                        list(zip(self.grads, self.local_network.var_list))
                    )
                    # Copy wheights back from local_prime to local:
                    self.sync_pi_from_pi_prime = tf.group(
                        *[v1.assign(v2) for v1, v2 in zip(self.local_network.var_list, self.local_network_prime.var_list)]
                    )
        except:
            msg = 'Child class 0.0 __init()__ exception occurred' + \
                '\n\nPress `Ctrl-C` or jupyter:[Kernel]->[Interrupt] for clean exit.\n'
            self.log.exception(msg)
            raise RuntimeError(msg)

    def start(self, sess, summary_writer, **kwargs):
        """
        Executes all initializing operations,
        starts environment runner[s].
        Supposed to be called by parent worker just before training loop starts.

        Args:
            sess:           tf session object.
            kwargs:         not used by default.
        """
        try:
            # Copy weights: global -> local -> meta:
            sess.run(self.sync_pi)
            sess.run(self.sync_pi_prime)
            # Start thread_runners:
            self._start_runners(sess, summary_writer)

        except:
            msg = 'Start() exception occurred' + \
                '\n\nPress `Ctrl-C` or jupyter:[Kernel]->[Interrupt] for clean exit.\n'
            self.log.exception(msg)
            raise RuntimeError(msg)

    def get_sample_config(self):
        """
        Returns environment configuration parameters for next episode to sample.
        Controls Trials and Episodes data distributions.

        Returns:
            configuration dictionary of type `btgym.datafeed.base.EnvResetConfig`
        """
        #sess = tf.get_default_session()

        if self.current_train_episode < self.num_train_episodes:
            episode_type = 0  # train
            self.current_train_episode += 1
            self.log.info(
                'training, c_train={}, c_test={}, type={}'.
                format(self.current_train_episode, self.current_test_episode, episode_type)
            )
        else:
            if self.current_test_episode < self.num_test_episodes:
                episode_type = 1  # test
                self.current_test_episode += 1
                self.log.info(
                    'meta-training, c_train={}, c_test={}, type={}'.
                    format(self.current_train_episode, self.current_test_episode, episode_type)
                )
            else:
                # single cycle end, reset counters:
                self.current_train_episode = 0
                self.current_test_episode = 0
                if self.cycles_counter < self.cycles_per_trial:
                    cycle_start_sample_config = dict(
                        episode_config=dict(
                            get_new=True,
                            sample_type=0,
                            b_alpha=1.0,
                            b_beta=1.0
                        ),
                        trial_config=dict(
                            get_new=False,
                            sample_type=0,
                            b_alpha=1.0,
                            b_beta=1.0
                        )
                    )
                    self.cycles_counter += 1
                    self.log.info(
                        'training (new cycle), c_train={}, c_test={}, type={}'.
                            format(self.current_train_episode, self.current_test_episode, 0)
                    )
                    return cycle_start_sample_config

                else:
                    init_sample_config = dict(
                        episode_config=dict(
                            get_new=True,
                            sample_type=0,
                            b_alpha=1.0,
                            b_beta=1.0
                        ),
                        trial_config=dict(
                            get_new=True,
                            sample_type=0,
                            b_alpha=1.0,
                            b_beta=1.0
                        )
                    )
                    self.cycles_counter = 1
                    self.log.info('new Trial at {}-th local iteration'.format(self.local_steps))
                    return init_sample_config

        # Compose btgym.datafeed.base.EnvResetConfig-consistent dict:
        sample_config = dict(
            episode_config=dict(
                get_new=True,
                sample_type=episode_type,
                b_alpha=1.0,
                b_beta=1.0
            ),
            trial_config=dict(
                get_new=False,
                sample_type=0,
                b_alpha=1.0,
                b_beta=1.0
            )
        )
        return sample_config

    def process(self, sess):
        """
        Overrides default
        """
        try:
            # Collect data from child thread runners:
            data = self._get_data()

            # Test or train: if at least one on-policy rollout from parallel runners is test one -
            # set learn rate to zero for entire minibatch. Doh.
            try:
                is_train = not np.asarray([env['state']['metadata']['type'] for env in data['on_policy']]).any()

            except KeyError:
                is_train = True

            # New or same trial:
            # If at least one trial number from parallel runners has changed - assume new cycle start:
            # Pull trial number's from on_policy metadata:
            trial_num = np.asarray([env['state']['metadata']['trial_num'][-1] for env in data['on_policy']])
            if (trial_num != self.current_trial_num).any():
                # Copy global -> local:
                sess.run(self.sync_pi)
                self.log.debug(
                    'New Trial_{}, local<-global update at {}-th local iteration'.format(trial_num, self.local_steps))
                self.current_trial_num = trial_num

            feed_dict = self.process_data(sess, data, is_train=True)

            # Say `No` to redundant summaries:
            wirte_model_summary =\
                self.local_steps % self.model_summary_freq == 0

            if is_train:
                # Train locally:
                fetches = [self.meta_train_op]
                self.log.debug(
                    'local<-d.local update at {}-th local iteration'.format(self.local_steps)
                )
            else:
                # Restore: local_prime -> local:
                sess.run(self.sync_pi_from_pi_prime)
                fetches = [self.train_op]
                self.log.debug(
                    'global<-d.local(~local_prime) update at {}-th local iteration'.format(self.local_steps)
                )

            if wirte_model_summary:
                fetches_last = fetches + [self.model_summary_op, self.inc_step]
            else:
                fetches_last = fetches + [self.inc_step]

            # Do a number of SGD train epochs: HERE==1 !
            # When doing more than one epoch, we actually use only last summary:
            for i in range(self.num_epochs - 1):
                fetched = sess.run(fetches, feed_dict=feed_dict)

            fetched = sess.run(fetches_last, feed_dict=feed_dict)

            if is_train:
                # Back up local -> local_prime:
                sess.run(self.sync_pi_prime)
                self.log.debug(
                    'local_prime<-local update at {}-th local iteration'.format(self.local_steps)
                )

            if wirte_model_summary:
                model_summary = fetched[-2]

            else:
                model_summary = None

            # Write down summaries:
            self.process_summary(sess, data, model_summary)

            self.local_steps += 1

        except:
            msg = 'Train step exception occurred' + \
                '\n\nPress `Ctrl-C` or jupyter:[Kernel]->[Interrupt] for clean exit.\n'
            self.log.exception(msg)
            raise RuntimeError(msg)


class MetaA3C_0_1(MetaA3C_0_0):
    """
    0_0 +: enable: local model got updated after every meta-optimization update.
    """

    def __init__(self, **kwargs):
        super(MetaA3C_0_1, self).__init__(**kwargs)

    def process(self, sess):
        """
        Overrides default
        """
        try:
            # Collect data from child thread runners:
            data = self._get_data()

            # Test or train: if at least one on-policy rollout from parallel runners is test one -
            # set learn rate to zero for entire minibatch. Doh.
            try:
                is_train = not np.asarray([env['state']['metadata']['type'] for env in data['on_policy']]).any()

            except KeyError:
                is_train = True

            # New or same trial:
            # If at least one trial number from parallel runners has changed - assume new cycle start:
            # Pull trial number's from on_policy metadata:
            trial_num = np.asarray([env['state']['metadata']['trial_num'][-1] for env in data['on_policy']])
            if (trial_num != self.current_trial_num).any():
                # Copy global -> local:
                sess.run(self.sync_pi)
                self.log.debug(
                    'New Trial_{}, local<-global update at {}-th local iteration'.format(trial_num, self.local_steps))
                self.current_trial_num = trial_num

            feed_dict = self.process_data(sess, data, is_train=True)

            # Say `No` to redundant summaries:
            wirte_model_summary =\
                self.local_steps % self.model_summary_freq == 0

            if is_train:
                # Train locally:
                fetches = [self.meta_train_op]
                self.log.debug(
                    'local<-d.local update at {}-th local iteration'.format(self.local_steps)
                )
            else:
                # Meta training, restore local_prime -> local: use stored after last local train update parameters:
                sess.run(self.sync_pi_from_pi_prime)
                fetches = [self.train_op]
                self.log.debug(
                    'global<-d.local(~local_prime) update at {}-th local iteration'.format(self.local_steps)
                )

            if wirte_model_summary:
                fetches_last = fetches + [self.model_summary_op, self.inc_step]
            else:
                fetches_last = fetches + [self.inc_step]

            # Do a number of SGD train epochs: HERE==1 !
            # When doing more than one epoch, we actually use only last summary:
            for i in range(self.num_epochs - 1):
                fetched = sess.run(fetches, feed_dict=feed_dict)

            fetched = sess.run(fetches_last, feed_dict=feed_dict)

            if is_train:
                # Back up updated local -> local_prime after local train step:
                sess.run(self.sync_pi_prime)
                self.log.debug(
                    'local_prime<-local update at {}-th local iteration'.format(self.local_steps)
                )
            else:
                # Copy global -> local for the next train cycle,
                # redundant if doing several meta-updates in a cycle (only last counts):
                sess.run(self.sync_pi)
                self.log.debug(
                    'local<-global update at {}-th local iteration'.format(trial_num, self.local_steps))

            if wirte_model_summary:
                model_summary = fetched[-2]

            else:
                model_summary = None

            # Write down summaries:
            self.process_summary(sess, data, model_summary)

            self.local_steps += 1

        except:
            msg = 'Train step exception occurred' + \
                '\n\nPress `Ctrl-C` or jupyter:[Kernel]->[Interrupt] for clean exit.\n'
            self.log.exception(msg)
            raise RuntimeError(msg)


class MetaCriticA3C_0_0(BaseAAC):
    """
    Meta-critic update
    """

    def __init__(self, cycles_per_trial=1, _log_name='MetaCriticA3C_0.0', **kwargs):
        """

        Args:
            cycles_per_trial (int):         outer loop
            kwargs:                         BaseAAC kwargs
        """
        try:
            super(MetaCriticA3C_0_0, self).__init__(_log_name=_log_name, **kwargs)
            self.current_trial_num = -1
            self.cycles_per_trial = cycles_per_trial
            self.cycles_counter = 1
            with tf.device(self.worker_device):
                with tf.variable_scope('local'):
                    # Make meta -optimizer and -train op:
                    # TODO: here should be beta step-size:
                    self.meta_optimizer = tf.train.AdamOptimizer(self.learn_rate_decayed, epsilon=1e-5)
                    self.meta_grads, _ = tf.clip_by_global_norm(
                        tf.gradients(self.loss, self.local_network.meta_critic_var_list),
                        40.0
                    )
                    self.meta_train_op = self.meta_optimizer.apply_gradients(
                        list(zip(self.meta_grads, self.network.meta_critic_var_list))
                    )
                    # Copy wheights back from local_prime to local:
                    #self.sync_pi_from_pi_prime = tf.group(
                    #    *[v1.assign(v2) for v1, v2 in
                    #      zip(self.local_network.var_list, self.local_network_prime.var_list)]
                    #)
        except:
            msg = 'Child 0.0 class __init()__ exception occurred' + \
                  '\n\nPress `Ctrl-C` or jupyter:[Kernel]->[Interrupt] for clean exit.\n'
            self.log.exception(msg)
            raise RuntimeError(msg)

    def start(self, sess, summary_writer, **kwargs):
        """
        Executes all initializing operations,
        starts environment runner[s].
        Supposed to be called by parent worker just before training loop starts.

        Args:
            sess:           tf session object.
            kwargs:         not used by default.
        """
        try:
            # Copy weights: global -> local -> meta:
            sess.run(self.sync_pi)
            # Start thread_runners:
            self._start_runners(sess, summary_writer)

        except:
            msg = 'Start() exception occurred' + \
                '\n\nPress `Ctrl-C` or jupyter:[Kernel]->[Interrupt] for clean exit.\n'
            self.log.exception(msg)
            raise RuntimeError(msg)

    def get_sample_config(self):
        """
        Returns environment configuration parameters for next episode to sample.
        Controls Trials and Episodes data distributions.

        Returns:
            configuration dictionary of type `btgym.datafeed.base.EnvResetConfig`
        """
        #sess = tf.get_default_session()

        if self.current_train_episode < self.num_train_episodes:
            episode_type = 0  # train
            self.current_train_episode += 1
            self.log.info(
                'training, c_train={}, c_test={}, type={}'.
                format(self.current_train_episode, self.current_test_episode, episode_type)
            )
        else:
            if self.current_test_episode < self.num_test_episodes:
                episode_type = 1  # test
                self.current_test_episode += 1
                self.log.info(
                    'meta-training, c_train={}, c_test={}, type={}'.
                    format(self.current_train_episode, self.current_test_episode, episode_type)
                )
            else:
                # single cycle end, reset counters:
                self.current_train_episode = 0
                self.current_test_episode = 0
                if self.cycles_counter < self.cycles_per_trial:
                    cycle_start_sample_config = dict(
                        episode_config=dict(
                            get_new=True,
                            sample_type=0,
                            b_alpha=1.0,
                            b_beta=1.0
                        ),
                        trial_config=dict(
                            get_new=False,
                            sample_type=0,
                            b_alpha=1.0,
                            b_beta=1.0
                        )
                    )
                    self.cycles_counter += 1
                    self.log.info(
                        'training (new cycle), c_train={}, c_test={}, type={}'.
                            format(self.current_train_episode, self.current_test_episode, 0)
                    )
                    return cycle_start_sample_config

                else:
                    init_sample_config = dict(
                        episode_config=dict(
                            get_new=True,
                            sample_type=0,
                            b_alpha=1.0,
                            b_beta=1.0
                        ),
                        trial_config=dict(
                            get_new=True,
                            sample_type=0,
                            b_alpha=1.0,
                            b_beta=1.0
                        )
                    )
                    self.cycles_counter = 1
                    self.log.info('new Trial at {}-th local iteration'.format(self.local_steps))
                    return init_sample_config

        # Compose btgym.datafeed.base.EnvResetConfig-consistent dict:
        sample_config = dict(
            episode_config=dict(
                get_new=True,
                sample_type=episode_type,
                b_alpha=1.0,
                b_beta=1.0
            ),
            trial_config=dict(
                get_new=False,
                sample_type=0,
                b_alpha=1.0,
                b_beta=1.0
            )
        )
        return sample_config

    def process(self, sess):
        """
        Overrides default
        """
        try:
            # Collect data from child thread runners:
            data = self._get_data()

            # Test or train: if at least one on-policy rollout from parallel runners is test one -
            # set learn rate to zero for entire minibatch. Doh.
            try:
                is_train = not np.asarray([env['state']['metadata']['type'] for env in data['on_policy']]).any()

            except KeyError:
                is_train = True

            # New or same trial:
            # If at least one trial number from parallel runners has changed - assume new cycle start:
            # Pull trial number's from on_policy metadata:
            #trial_num = np.asarray([env['state']['metadata']['trial_num'][-1] for env in data['on_policy']])
            #if (trial_num != self.current_trial_num).any():
            #    # Copy global -> local:
            #    sess.run(self.sync_pi)
            #    self.log.info(
            #        'New Trial_{}, local<-global update at {}-th local iteration'.format(trial_num, self.local_steps))
            #    self.current_trial_num = trial_num

            feed_dict = self.process_data(sess, data, is_train=True)

            # Say `No` to redundant summaries:
            wirte_model_summary = \
                self.local_steps % self.model_summary_freq == 0

            # Update parameters from global:
            sess.run(self.sync_pi)

            if is_train:
                # Perform regular a3c routine:
                fetches = [self.train_op]
                self.log.info(
                    'global<-d.local update at {}-th local iteration'.format(self.local_steps)
                )
            else:
                # Meta training on test data, only send meta-critic gradients subset to global:
                fetches = [self.meta_train_op]
                self.log.info(
                    'global<-d.meta_local update at {}-th local iteration'.format(self.local_steps)
                )
            if wirte_model_summary:
                fetches_last = fetches + [self.model_summary_op, self.inc_step]
            else:
                fetches_last = fetches + [self.inc_step]

            # Do a number of SGD train epochs: HERE==1 !
            # When doing more than one epoch, we actually use only last summary:
            for i in range(self.num_epochs - 1):
                fetched = sess.run(fetches, feed_dict=feed_dict)

            fetched = sess.run(fetches_last, feed_dict=feed_dict)

            if wirte_model_summary:
                model_summary = fetched[-2]

            else:
                model_summary = None

            # Write down summaries:
            self.process_summary(sess, data, model_summary)

            self.local_steps += 1

        except:
            msg = 'Train step exception occurred' + \
                  '\n\nPress `Ctrl-C` or jupyter:[Kernel]->[Interrupt] for clean exit.\n'
            self.log.exception(msg)
            raise RuntimeError(msg)


class MetaCriticA3C_0_1(MetaCriticA3C_0_0):
    """
    Meta-critic update,  train step restricted to actor update only.
    """

    def __init__(self, _log_name='MetaCriticA3C_0.1', **kwargs):
        """

        Args:
            cycles_per_trial (int):         outer loop
            kwargs:                         BaseAAC kwargs
        """
        try:
            super(MetaCriticA3C_0_1, self).__init__(_log_name=_log_name, **kwargs)
            with tf.device(self.worker_device):
                with tf.variable_scope('local'):
                    # Restrict base optimizer to actor part of the policy:
                    self.actor_grads, _ = tf.clip_by_global_norm(
                        tf.gradients(self.loss, self.local_network.actor_var_list),
                        40.0
                    )
                    self.train_op = self.optimizer.apply_gradients(
                        list(zip(self.actor_grads, self.network.actor_var_list))
                    )
                    # Copy wheights back from local_prime to local:
                    #self.sync_pi_from_pi_prime = tf.group(
                    #    *[v1.assign(v2) for v1, v2 in
                    #      zip(self.local_network.var_list, self.local_network_prime.var_list)]
                    #)
        except:
            msg = 'Child 0.1 class __init()__ exception occurred' + \
                  '\n\nPress `Ctrl-C` or jupyter:[Kernel]->[Interrupt] for clean exit.\n'
            self.log.exception(msg)
            raise RuntimeError(msg)


class Unreal_expl_0_0(BaseAAC):
    """
    Set specified workers as 'exploratory kernel' by forcing to repeatedly train on
    constrained data distribution for extended time.
    """
    def __init__(self, kernel_workers=(1,), kernel_period=500, **kwargs):
        """

        Args:
            kernel_workers:     list of workers to set as 'kernels'
            kernel_period:      number of episodes for kernel worker to spend on same distribution
            **kwargs:           BaseAAC kwargs
        """
        super(Unreal_expl_0_0, self).__init__(**kwargs)
        # If instance in the list - overrode data sampling parameters:
        if self.task == np.asarray(kernel_workers).any():
            self.num_train_episodes = kernel_period
            self.num_test_episodes = 0
            self.log.notice('set as exploration kernel with period: {} episodes.'.format(self.num_train_episodes))


