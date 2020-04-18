from typing import Optional
import importlib

import torch
from torch import nn

from archai.common.trainer import Trainer
from archai.common.config import Config
from archai.common.common import logger
from archai.datasets import data
from archai.nas.model_desc import ModelDesc
from archai.nas.cell_builder import CellBuilder
from archai.nas import nas_utils
from archai.common import ml_utils, utils

def eval_arch(conf_eval:Config, cell_builder:Optional[CellBuilder]):
    logger.pushd('eval_arch')

    # region conf vars
    conf_loader       = conf_eval['loader']
    model_filename    = conf_eval['model_filename']
    metric_filename    = conf_eval['metric_filename']
    conf_checkpoint = conf_eval['checkpoint']
    resume = conf_eval['resume']
    conf_train = conf_eval['trainer']
    # endregion

    device = torch.device(conf_eval['device'])

    if cell_builder:
        cell_builder.register_ops()

    model = create_model(conf_eval, device)

    # get data
    train_dl, _, test_dl = data.get_data(conf_loader)
    assert train_dl is not None and test_dl is not None

    checkpoint = nas_utils.create_checkpoint(conf_checkpoint, resume)
    trainer = Trainer(conf_train, model, device, checkpoint, aux_tower=True)
    train_metrics = trainer.fit(train_dl, test_dl)
    train_metrics.save(metric_filename)

    # save model
    if model_filename:
        model_filename = utils.full_path(model_filename)
        ml_utils.save_model(model, model_filename)

    logger.info({'model_save_path': model_filename})

    logger.popd()

def create_model(conf_eval:Config, device)->nn.Module:
    # region conf vars
    final_desc_filename = conf_eval['final_desc_filename']
    final_model_factory = conf_eval['final_model_factory']
    full_desc_filename = conf_eval['full_desc_filename']
    conf_model_desc   = conf_eval['model_desc']
    # endregion

    if final_model_factory:
        module_name = final_model_factory['module']
        function_name = final_model_factory['function']
        args = final_model_factory.get('args', {})

        module = importlib.import_module(module_name)
        function = getattr(module, function_name)
        model = function(**args)

        logger.info({'model_factory':True,
                    'module_name': module_name,
                    'function_name': function_name,
                    'params': ml_utils.param_size(model)})
    else:
        # load model desc file to get template model
        template_model_desc = ModelDesc.load(final_desc_filename)

        # TODO: move aux_tower, droppath into config
        model = nas_utils.model_from_conf(full_desc_filename,
                                    conf_model_desc, device,
                                    aux_tower=True, affine=True, droppath=True,
                                    template_model_desc=template_model_desc)

        logger.info({'model_factory':False,
                    'cells_len':len(model.desc.cell_descs()),
                    'init_ch_out': conf_model_desc['init_ch_out'],
                    'n_cells': conf_model_desc['n_cells'],
                    'n_reductions': conf_model_desc['n_reductions'],
                    'n_nodes': conf_model_desc['n_nodes']})

    return model



