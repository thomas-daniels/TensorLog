# (C) William W. Cohen and Carnegie Mellon University, 2016

import sys
import ops
import funs
import parser
import matrixdb
import bpcompiler
import logging
import getopt


#TODO make parameters of a program
MAXDEPTH=10
NORMALIZE=True

##############################################################################
## declarations
##############################################################################

class AbstractDeclaration(object):
    def __init__(self,goal):
        if type(goal)==type(""):
            goal = parser.Parser.parseGoal(goal)
        self.prototype = goal
        self._key = str(goal)
    def arg(self,i):
        return self.prototype.args[i]
    def getArity(self):
        return self.prototype.arity
    def getFunctor(self):
        return self.prototype.functor
    arity = property(getArity)
    functor = property(getFunctor)
    def __str__(self):
        return str(self.prototype)
    def __repr__(self):
        return repr(self.prototype)
    def __hash__(self):
        return hash(self._key)
    def __eq__(self,other):
        return other and isinstance(other,AbstractDeclaration) and self._key == other._key

class ModeDeclaration(AbstractDeclaration):
    """Declare a mode with a goal, eg hasWord(i1,o).  Arguments starting
    with 'i' (respectively 'o') are inputs (outputs), and arguments
    ending with '1' are one-hot encodings, aka singleton sets.
    """
    def isInput(self,i):
        return self.arg(i)=='i'
    def isOutput(self,i):
        return self.arg(i)=='o'
    def isConst(self,i):
        return not self.isInput(i) and not self.isOutput(i)

##############################################################################
## a program
##############################################################################

class Program(object):

    def __init__(self, db=None, rules=parser.RuleCollection()):
        self.db = db
        self.program = []
        self.function = {}
        self.rules = rules

    def findPredDef(self,mode):
        """Find the set of rules with a lhs that match the given mode."""
        return self.rules.rulesFor(mode)

    def compile(self,mode,depth=0):
        """ Produce an ops.Function object which implements the predicate definition
        """
        #find the rules which define this predicate/function
        
        if depth>MAXDEPTH:
            self.function[(mode,depth)] = funs.NullFunction(mode)
        else:
            predDef = self.findPredDef(mode)
            if len(predDef)==0:
                assert False,'no rules match mode %s' % mode
            elif len(predDef)==1:
                #instead of a sum of one function, just find the function
                #for this single predicate
                c = bpcompiler.BPCompiler(mode,self,depth,predDef[0])
                self.function[(mode,depth)] = c.getFunction()
            else:
                #compute a function that will sum up the values of the
                #clauses
                ruleFuns = map(lambda r:bpcompiler.BPCompiler(mode,self,depth,r).getFunction(), predDef)
                self.function[(mode,depth)] = funs.SumFunction(ruleFuns)
            if depth==0 and NORMALIZE:
                self.function[(mode,0)] = funs.NormalizedFunction(self.function[(mode,0)])
        return self.function[(mode,depth)]

    def listing(self):
        self.rules.listing()
        self.db.listing()

    def functionListing(self):
        for (m,d) in sorted(self.function.keys()):
            print '> mode',m,'depth',d,'fun:',self.function[(m,d)]

    def getPredictFunction(self,mode):
        if (mode,0) not in self.function: self.compile(mode)
        fun = self.function[(mode,0)]
        return fun

    def evalSymbols(self,mode,symbols):
        """ After compilation, evaluate a function.  Input is a list of
        symbols that will be converted to onehot vectors, and bound to
        the corresponding input arguments.
        """
        return self.eval(mode, [self.db.onehot(s) for s in symbols])

    def eval(self,mode,inputs):
        """ After compilation, evaluate a function.  Input is a list of onehot
        vectors, which will be bound to the corresponding input
        arguments.
        """
        if (mode,0) not in self.function: self.compile(mode)
        fun = self.function[(mode,0)]
        return fun.eval(self.db, inputs)

    def evalGradSymbols(self,mode,symbols):
        """ After compilation, evaluate a function.  Input is a list of
        symbols that will be converted to onehot vectors, and bound to
        the corresponding input arguments.
        """
        return self.evalGrad(mode, [self.db.onehot(s) for s in symbols])

    def evalGrad(self,mode,inputs):
        """ After compilation, evaluate a function.  Input is a list of onehot
        vectors, which will be bound to the corresponding input
        arguments.
        """
        if (mode,0) not in self.function: self.compile(mode)
        fun = self.function[(mode,0)]
        return fun.evalGrad(self.db, inputs)

    @staticmethod 
    def _load(fileNames):
        ruleFiles = [f for f in fileNames if f.endswith(".ppr") or f.endswith(".tlog")]
        dbFiles = [f for f in fileNames if f.endswith(".db")]
        factFiles = [f for f in fileNames if f.endswith(".cfacts")]
        assert (not dbFiles) or (not factFiles), 'cannot combine a serialized database and .cfacts files'
        assert (not dbFiles) or (len(dbFiles)==1), 'cannot combine multiple serialized databases'
        assert dbFiles or factFiles,'no db specified'
        assert ruleFiles,'no rules specified'
        rules = parser.Parser.parseFile(ruleFiles[0])
        for f in ruleFiles[1:]:
            rules = parser.Parser.parseFile(f,rules)
        if dbFiles:
            db = matrixdb.MatrixDB.deserialize(dbFiles[0])
        if factFiles:
            db = matrixdb.MatrixDB()
            for f in factFiles:
                db.bufferFile(f)
                db.flushBuffers()
                db.clearBuffers()
        return (db,rules)

    @staticmethod
    def load(fileNames):
        (db,rules) = Program._load(fileNames)
        return Program(db,rules)

#
# subclass of Program that corresponds more or less to Proppr....
# 

class ProPPRProgram(Program):

    def __init__(self, db=None, rules=parser.RuleCollection(),weights=None):
        super(ProPPRProgram,self).__init__(db=db, rules=rules)
        #expand the syntactic sugar used by ProPPR
        self.rules.mapRules(ProPPRProgram._moveFeaturesToRHS)
        if weights!=None: self.setWeights(weights)

    def setWeights(self,weights):
        self.db.params[("weighted",1)] = self.db.insertPredicate(weights,"weighted",1)

    def getWeights(self):  
        return self.db.params[("weighted",1)]

    def getParams(self):
        return self.db.params

    @staticmethod
    def _moveFeaturesToRHS(rule0):
        rule = parser.Rule(rule0.lhs, rule0.rhs)
        if not rule0.findall:
            #parsed format is {f1,f2,...} but we only support {f1}
            assert len(rule0.features)==1,'multiple constant features not supported'
            constFeature = rule0.features[0].functor
            constAsVar = constFeature.upper()
            rule.rhs.append( matrixdb.assignGoal(constAsVar,constFeature) )
            rule.rhs.append( parser.Goal('weighted',[constAsVar]) )
        else:
            #format is {all(F):-...}
            assert len(rule0.features)==1,'feature generators of the form {a,b: ... } not supported'
            featureLHS = rule0.features[0]
            assert featureLHS.arity==1 and featureLHS.functor=='all', 'non-constant features must be of the form {all(X):-...}'
            outputVar = featureLHS.args[0] 
            for goal in rule0.findall:
                rule.rhs.append(goal)
            rule.rhs.append( parser.Goal('weighted',[outputVar]) )
        return rule

    @staticmethod
    def load(fileNames):
        (db,rules) = Program._load(fileNames)
        return ProPPRProgram(db,rules)

def answerStringQuery(p,a):
    """Use a program to answer a query and print the result - used in the sample main"""
    g = parser.Parser.parseGoal(a)
    assert (not parser.isVariableAtom(g.args[0]) and parser.isVariableAtom(g.args[1])), 'mode of query should be p(i,o): %s' % str(g)
    mode = ModeDeclaration(parser.Goal(g.functor,['i','o']))
    x = g.args[0]
    result = p.evalSymbols(mode,[x])
    print p.db.rowAsSymbolDict(result)

#
# sample main: python tensorlog.py test/fam.cfacts 'rel(i,o)' 'rel(X,Y):-spouse(X,Y).' william
#

if __name__ == "__main__":
    
    argspec = ["programFiles="]
    try:
        optlist,args = getopt.getopt(sys.argv[1:], 'x', argspec)
    except getopt.GetoptError:
        logging.fatal('bad option: use "--help" to get help')
        sys.exit(-1)
    optdict = dict(optlist)

    assert '--programFiles' in optdict, '--programFiles f1:f2:... is a required option'

    p = Program.load(optdict['--programFiles'].split(":"))

    for a in args:
        answerStringQuery(p,a)
