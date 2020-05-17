from typing import Iterable, Optional, Tuple, List
from collections import deque

import torch
from torch import nn
import torch.nn.functional as F

import numpy as np
import h5py

from overrides import overrides

from archai.nas.model_desc import OpDesc
from archai.nas.operations import Op
from archai.common.common import get_conf

# TODO: reduction cell might have output reduced by 2^1=2X due to
#   stride 2 through input nodes however FactorizedReduce does only
#   4X reduction. Is this correct?


class DivOp(Op):
    """The output of DivOp is weighted output of all allowed primitives.
    """

    PRIMITIVES = [
        'max_pool_3x3',
        'avg_pool_3x3',
        'skip_connect',  # identity
        'sep_conv_3x3',
        'sep_conv_5x5',
        'dil_conv_3x3',
        'dil_conv_5x5',
        'none'  # this must be at the end so top1 doesn't choose it
    ]

    # list of primitive ops not allowed in the 
    # diversity calculation
    # NOTALLOWED = ['skip_connect', 'none']
    NOTALLOWED = ['none']

    def _indices_of_notallowed(self):
        ''' computes indices of notallowed ops in PRIMITIVES '''
        self._not_allowed_indices = []
        for op_name in self.NOTALLOWED:
            self._not_allowed_indices.append(self.PRIMITIVES.index(op_name))
        self._not_allowed_indices = sorted(self._not_allowed_indices, reverse=True)

    def _create_mapping_valid_to_orig(self):
        ''' Creates a list with indices of the valid ops to the original list '''
        self._valid_to_orig = []
        for i, prim in enumerate(self.PRIMITIVES):
            if prim in self.NOTALLOWED:
                continue
            else:
                self._valid_to_orig.append(i)

    def __init__(self, op_desc:OpDesc, alphas: Iterable[nn.Parameter],
                 affine:bool):
        super().__init__()

        # assume last PRIMITIVE is 'none'
        assert DivOp.PRIMITIVES[-1] == 'none'

        conf = get_conf()
        trainer = conf['nas']['search']['divnas']['archtrainer']
        finalizer = conf['nas']['search']['finalizer']

        if trainer == 'noalpha' and finalizer == 'default':
            raise NotImplementedError

        if trainer != 'noalpha':
            self._set_alphas(alphas)
        else:
            self._alphas = None

        self._ops = nn.ModuleList()
        for primitive in DivOp.PRIMITIVES:
            op = Op.create(
                OpDesc(primitive, op_desc.params, in_len=1, trainables=None),
                affine=affine, alphas=alphas)
            self._ops.append(op)

        # various state variables for diversity
        self._collect_activations = False
        self._forward_counter = 0
        self._batch_activs = None
        self._indices_of_notallowed()
        self._create_mapping_valid_to_orig()

    @property
    def collect_activations(self)->bool:
        return self._collect_activations

    @collect_activations.setter
    def collect_activations(self, to_collect:bool)->None:
        self._collect_activations = to_collect

    @property
    def activations(self)->Optional[List[np.array]]:
        return self._batch_activs

    @property
    def num_valid_div_ops(self)->int:
        return len(self.PRIMITIVES) - len(self.NOTALLOWED)
        
    @overrides
    def forward(self, x):
    
        # save activations to object
        if self._collect_activations:
            self._forward_counter += 1
            activs = [op(x) for op in self._ops]
            self._batch_activs = [t.cpu().detach().numpy() for t in activs]
            # delete the activations that are not allowed
            for index in self._not_allowed_indices:
                del self._batch_activs[index]

        if self._alphas:
            asm = F.softmax(self._alphas[0], dim=0)
            result = sum(w * op(x) for w, op in zip(asm, self._ops))
        else:
            result = sum(op(x) for op in self._ops)
            
        return result

    @overrides
    def alphas(self) -> Iterable[nn.Parameter]:
        if self._alphas:
            for alpha in self._alphas:
                yield alpha

    @overrides
    def weights(self) -> Iterable[nn.Parameter]:
        for op in self._ops:
            for w in op.parameters():
                yield w


    def get_op_desc(self, index:int)->OpDesc:
        ''' index: index in the primitives list '''
        assert index < len(self.PRIMITIVES)
        desc, _ = self._ops[index].finalize()
        return desc


    def get_valid_op_desc(self, index:int)->OpDesc:
        ''' index: index in the valid index list '''
        assert index <= self.num_valid_div_ops
        orig_index = self._valid_to_orig[index]        
        desc, _ = self._ops[orig_index].finalize()
        return desc


    @overrides
    def can_drop_path(self) -> bool:
        return False

    def _set_alphas(self, alphas: Iterable[nn.Parameter]) -> None:
        # must call before adding other ops
        assert len(list(self.parameters())) == 0
        self._alphas = list(alphas)
        if not len(self._alphas):
            new_p = nn.Parameter(  # TODO: use better init than uniform random?
                1.0e-3*torch.randn(len(DivOp.PRIMITIVES)), requires_grad=True)
            # NOTE: This is a way to register parameters with PyTorch.
            # One creates a dummy variable with the parameters and then
            # asks back for the parameters in the object from Pytorch
            # which automagically registers the just created parameters.
            self._reg_alphas = new_p
            self._alphas = [p for p in self.parameters()]