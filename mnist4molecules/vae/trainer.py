import numpy as np
import torch.optim as optim
import tqdm
from torch.nn.utils import clip_grad_norm_

from mnist4molecules.vae.misc import CosineAnnealingLRWithRestart, KLAnnealer, \
    Logger


class VAETrainer:
    def __init__(self, config):
        self.config = config

    def fit(self, model, data):
        model.train()

        n_epoch = self._n_epoch()
        kl_annealer = KLAnnealer(n_epoch, self.config)
        get_params = lambda: (p for p in model.vae.parameters()
                              if p.requires_grad)
        optimizer = optim.Adam(get_params(), lr=self.config.lr_start)
        lr_annealer = CosineAnnealingLRWithRestart(optimizer, self.config)

        T = tqdm.tqdm(range(n_epoch))
        n_iter, n_last = len(data), self.config.n_last
        elog, ilog = Logger(), Logger()

        for epoch in T:
            # Epoch start
            kl_weight = kl_annealer(epoch)

            # Iters
            for i, x in enumerate(data):
                # Forward
                kl_loss, recon_loss = model(x)
                loss = kl_weight * kl_loss + recon_loss

                # Backward
                optimizer.zero_grad()
                loss.backward()
                clip_grad_norm_(get_params(), self.config.grad_clipping)
                optimizer.step()

                # Log
                lr = optimizer.param_groups[0]['lr']
                ilog.append({
                    'epoch': epoch,
                    'kl_loss': kl_loss.item(),
                    'recon_loss': recon_loss.item(),
                    'loss': loss.item(),
                    'kl_weight': kl_weight,
                    'lr': lr
                })

                # Update T
                kl_loss_value = np.mean(ilog['kl_loss'][-n_last:])
                recon_loss_value = np.mean(ilog['recon_loss'][-n_last:])
                loss_value = np.mean(ilog['loss'][-n_last:])
                postfix_strs = [f'i={i}/{n_iter}',
                                f'loss={loss_value:.5f}',
                                f'(kl={kl_loss_value:.5f}',
                                f'recon={recon_loss_value:.5f})',
                                f'klw={kl_weight:.2f} lr={lr:.5f}']
                T.set_postfix_str(' '.join(postfix_strs))
                T.refresh()

            # Log
            elog.append({
                **{k: v for k, v in ilog[-1].items() if 'loss' not in k},
                'kl_loss': kl_loss_value,
                'recon_loss': recon_loss_value,
                'loss': loss_value
            })

            # Print result
            print(f"epoch={epoch}")

            # Epoch end
            lr_annealer.step()

        return elog, ilog

    def _n_epoch(self):
        return sum(
            self.config.lr_n_period * (self.config.lr_n_mult ** i)
            for i in range(self.config.lr_n_restarts)
        )