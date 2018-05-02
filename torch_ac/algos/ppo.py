import random
import torch
import torch.nn.functional as F

from torch_ac.algos.base import BaseAlgo
from torch_ac.utils.batch import batchify

class PPOAlgo(BaseAlgo):
    def __init__(self, envs, acmodel, num_frames_per_proc=None, discount=0.99, lr=7e-4, gae_tau=0.95,
                 entropy_coef=0.01, value_loss_coef=0.5, max_grad_norm=0.5, recurrence=4,
                 adam_eps=1e-5, clip_eps=0.2, epochs=4, batch_size=256, preprocess_obss=None,
                 reshape_reward=None):
        num_frames_per_proc = num_frames_per_proc or 128

        super().__init__(envs, acmodel, num_frames_per_proc, discount, lr, gae_tau, entropy_coef,
                         value_loss_coef, max_grad_norm, recurrence, preprocess_obss, reshape_reward)

        self.clip_eps = clip_eps
        self.epochs = epochs
        self.batch_size = batch_size

        self.optimizer = torch.optim.Adam(self.acmodel.parameters(), lr, eps=adam_eps)
    
    def update_parameters(self):
        # Collect transitions

        ts, log = self.collect_transitions()

        for _ in range(self.epochs):
            for b in batchify(ts, self.batch_size):
                # Compute loss

                if self.is_recurrent:
                    dist, value, _ = self.acmodel(b.obs, b.state * b.mask)
                else:
                    dist, value = self.acmodel(b.obs)

                entropy = dist.entropy()

                ratio = torch.exp(dist.log_prob(b.action) - b.log_prob)
                surr1 = ratio * b.advantage
                surr2 = torch.clamp(ratio, 1.0 - self.clip_eps, 1.0 + self.clip_eps) * b.advantage
                policy_loss = -torch.min(surr1, surr2).mean()

                value_clipped = b.value + torch.clamp(value - b.value, -self.clip_eps, self.clip_eps)
                surr1 = (value - b.returnn).pow(2)
                surr2 = (value_clipped - b.returnn).pow(2)
                value_loss = torch.max(surr1, surr2).mean()

                loss = policy_loss - self.entropy_coef * entropy.mean() + self.value_loss_coef * value_loss

                # Update actor-critic

                self.optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.acmodel.parameters(), self.max_grad_norm)
                self.optimizer.step()
        
        # Log some values

        log["entropy"] = entropy.mean().item()
        log["value"] = value.mean().item()
        log["policy_loss"] = policy_loss.item()
        log["value_loss"] = value_loss.item()

        return log