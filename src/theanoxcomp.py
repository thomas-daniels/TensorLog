import tensorlog
import funs
import ops
import matrixdb
import declare
import mutil

import theano
import theano.tensor as TT
import theano.tensor.nnet as TNN
import theano.sparse as TS
import theano.sparse.basic as TSB
from theano.ifelse import ifelse
import numpy as NP

class TheanoEnv(object):

    """A 'namespaced' dictionary indexed by strings. Assigns every string
    to an 'internalName' which depends on the string and the
    namespaceId for this object, and indexes by that internal name.
    The internal names are assigned to keep the local variable names
    from distinct OpSeqFunction's environments from clashing, when
    they are converted to theano variables with assigned names.
    """
    def __init__(self,namespaceId):
        self.namespaceId = namespaceId
        self.env = {}
    def internalName(self,key):
        return 'n%d__%s' % (self.namespaceId,key)
    def __getitem__(self,key):
        return self.env[self.internalName(key)]
    def __setitem__(self,key,val):
        self.env[self.internalName(key)] = val

class CrossCompiler(object):

    def __init__(self,db):
        # namespaces are integer
        self.nameSpace = 0
        # dbMatrixExpr is a cache mapping a (mode,transposeFlag) pair --
        # which determine a matrix from the matrixdb -- to a theano
        # variable that should be bound to that matrix
        self.dbMatrixExpr = {}
        # maps a (mode,transposeFlag) pair to the matrix that the
        # corresponding dbMatrixExpr should be bound to
        self.dbMatrixExprBinding = {}
        # hold the database
        self.db = db
        #
        # stuff below is set by compile
        #
        # a theano expression implementing the tensorlog function, and
        # the theano variable which is the input argument(s) to
        # tensorlog function
        self.exprArgs = self.expr = None
        # the theano variables for the matrixdb matrices used in the
        # expression, and the values to which they should be bound
        self.dbArgs = self.dbVals = None
        # theano function
        self.thFun = None

    def allocNamespace(self):
        """Allocate a new name space.
        """
        result = self.nameSpace
        self.nameSpace += 1
        return result

    def show(self):
        print 'exprArgs',self.exprArgs
        print 'expr',theano.pp(self.expr)
        print len(self.dbArgs),'db param(s):'
        for i in range(len(self.dbArgs)):
            print ' |',self.dbArgs[i],mutil.summary(self.dbVals[i])
        print 'fun',theano.pp(self.thFun.maker.fgraph.outputs[0])
        print 'debuug fun',theano.printing.debugprint(self.thFun.maker.fgraph.outputs[0])

    def compile(self,fun,numInputs=1):
        (self.exprArgs,self.expr) = self.fun2Expr(fun,numInputs=numInputs)
        self.dbArgs = []
        self.dbVals = []
        for key in sorted(self.dbMatrixExpr):
            self.dbArgs.append(self.dbMatrixExpr[key])
            self.dbVals.append(self.dbMatrixExprBinding[key])
        self.args = self.exprArgs + self.dbArgs
        self.thFun = theano.function(inputs=self.args, outputs=self.expr)

    def matrixExpr(self,matMode):
        """Return a theano expression that denotes the matrix retrieved by
        the (matMode, transpose) pair using the matrixdb
        """ 
        if (matMode) not in self.dbMatrixExpr:
            u = "M__" + matMode.getFunctor() +"_" + "".join([matMode.arg(i) for i in range(matMode.getArity())])
            self.dbMatrixExpr[matMode] = TT.dmatrix(u)
            self.dbMatrixExprBinding[matMode] = self.db.matrix(matMode,False)
        return self.dbMatrixExpr[matMode]

    def fun2Expr(self,fun,numInputs=1):
        """Return a pair (inputs, expr) where binding the inputs in theano,
        and then evaluating the expression, is roughly equivalent to
        evaluating the Function fun in tensorlog.  It's only roughly
        equivalent because one also needs to bind the necessary
        variables from the matrixdb to their values.
        """ 

        if isinstance(fun,funs.SoftmaxFunction):
            # wrap inner function with softmax function
            #print "softMax..."
            inputs,subExpr = self.fun2Expr(fun.fun,numInputs)
            # tricky: in our softmax code, we mask the results to keep 0 entries 0
            # before normalizing :-/
            result = TNN.nnet.softmax(subExpr) * (1 - TT.isclose(subExpr,TT.zeros_like(subExpr)))
            return (inputs, result / result.sum())

        elif isinstance(fun,funs.OpSeqFunction):
            assert len(fun.opInputs)==numInputs, 'mismatching number of inputs'
            # thEnv, a 'theano environment', maps nameSpaced variables
            # from the OpSeqFunction's environment to the
            # corresponding theano subexpressions
            thEnv = TheanoEnv(self.allocNamespace())
            # create the list of theano variables which should be used
            # as inputs to the expression
            seqInputs = []
            for v in fun.opInputs:
                thEnv[v] = TT.dmatrix(thEnv.internalName(v)) # dvector?
                seqInputs.append(thEnv[v])
            # fill in the theano environment appropriately
            for op in fun.ops:
                thEnv[op.dst] = self.op2Expr(thEnv,op)
            # return the inputs and the expression for the
            # OpSeqFunction's output
            return (seqInputs, thEnv[fun.ops[-1].dst])
        
        else:
            assert False,'cannot cross-compile %r' % fun
    
    def op2Expr(self,thEnv,op):
        """Extend the theano environment with an expression for the
        destination of the Operator.
        """
        
        if isinstance(op,ops.VecMatMulOp):
            mExpr = self.matrixExpr(op.matMode)
            if op.transpose:
                mExpr = mExpr.T
            return thEnv[op.src].dot(mExpr)
        else:
            assert False,'cannot cross-compile %r' % op
