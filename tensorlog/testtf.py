# (C) William W. Cohen and Carnegie Mellon University, 2017

# tensorflowxcomp specific tests

import os
import unittest
import sys
from tensorlog import xctargets
if xctargets.tf:
  import tensorflow as tf

from tensorlog import simple
from tensorlog import matrixdb
from tensorlog import dbschema
from tensorlog import program
from tensorlog import declare
from tensorlog import testtensorlog

@unittest.skipUnless(xctargets.tf,"Tensorflow not available")
class TestReuse(unittest.TestCase):

  def setUp(self):
    b = simple.Builder()
    p,q,sister,child = b.predicates("p q sister child")
    X,Y,Z = b.variables("X Y Z")
    b += p(X,Y) <= sister(X,Z) & child(Z,Y)
    b += q(X,Y) <= sister(X,Y)
    factFile = os.path.join(testtensorlog.TEST_DATA_DIR,"fam.cfacts")
    self.tlog = simple.Compiler(db=factFile, prog=b.rules)

  def testCombinePC(self):
    """ Check that we can reuse the inputs from one tensorlog function in another.
    """
    self.f1 = self.tlog.proof_count("p/io")
    self.f2 = self.tlog.proof_count("q/io", inputs=[self.tlog.input_placeholder("p/io")])
    self.g = (2*self.f1 + self.f2)
    self.checkBehavior()

  def testCombineInf(self):
    _1 = self.tlog.inference("p/io")
    _2 = self.tlog.inference("q/io", inputs=[self.tlog.input_placeholder("p/io")])
    self.f1 = self.tlog.proof_count("p/io")
    self.f2 = self.tlog.proof_count("q/io")
    self.g = (2*self.f1 + self.f2)
    self.checkBehavior()

  def testCombineLoss(self):

    _1 = self.tlog.loss("p/io")
    _2 = self.tlog.loss("q/io", inputs=[self.tlog.input_placeholder("p/io")])
    self.f1 = self.tlog.proof_count("p/io")
    self.f2 = self.tlog.proof_count("q/io")
    self.g = (2*self.f1 + self.f2)
    self.checkBehavior()

  def checkBehavior(self):
    tlog = self.tlog
    self.assertTrue(tlog.input_placeholder("p/io") is tlog.input_placeholder("q/io"))

    session = tf.Session()
    session.run(tf.global_variables_initializer())

    x = tlog.db.onehot("william").todense()
    input_name = tlog.input_placeholder_name("p/io")
    y1 = session.run(self.f1, feed_dict={input_name:x})
    dy1 = tlog.db.matrixAsSymbolDict(tlog.xc.unwrapOutput(y1))
    y2 = session.run(self.f2, feed_dict={input_name:x})
    dy2 = tlog.db.matrixAsSymbolDict(tlog.xc.unwrapOutput(y2))
    s = session.run(self.g, feed_dict={input_name:x})
    ds = tlog.db.matrixAsSymbolDict(tlog.xc.unwrapOutput(s))
    self.check_dicts(dy1, {'charlotte': 1.0, 'elizabeth': 1.0, 'caroline': 1.0, 'lucas': 1.0, 'poppy': 1.0})
    self.check_dicts(dy2, {'sarah': 1.0, 'rachel': 1.0, 'lottie': 1.0})
    self.check_dicts(ds,  {'sarah': 1.0, 'charlotte': 2.0, 'caroline': 2.0, 'lucas': 2.0, 'rachel': 1.0, 
                           'poppy': 2.0, 'lottie': 1.0, 'elizabeth': 2.0})

  def check_dicts(self,actualMat, expected):
    actual = actualMat[0]
    print('actual:  ',actual)
    print('expected:',expected)
    self.assertEqual(len(list(actual.keys())), len(list(expected.keys())))
    for k in list(actual.keys()):
      self.assertAlmostEqual(actual[k], expected[k], delta=0.05)

# stuck in here because I use Builder, lazy me
class TestTypeInference(unittest.TestCase):

  def testNest(self):
    b = simple.Builder()
    answer,about,actor,mention = b.predicates("answer,about,actor,mention")
    Q,M,A = b.variables("Q,M,A")
    b.rules += answer(Q,M) <= about(Q,A) & actor(M,A)
    b.rules += about(Q,A) <= mention(Q,A)
    b.rules.listing()
    db = matrixdb.MatrixDB(initSchema=dbschema.TypedSchema())
    db.addLines([ "# :- answer(query_t,movie_t)\n",
                  "# :- mention(query_t,actor_t)\n",
                  "# :- actor(actor_t,movie_t)\n",
                  '\t'.join(['mention','what_was_mel_brooks_in','mel_brooks']) + '\n',
                  '\t'.join(['actor','young_frankenstein','mel_brooks']) + '\n'
                  ])
    prog = program.Program(db=db, rules=b.rules)
    afun = prog.compile(declare.asMode("answer/io"))
    for t in afun.inputTypes:
      self.assertTrue(t is not None)
    bfun = prog.compile(declare.asMode("about/io"))
    for t in bfun.inputTypes:
      self.assertTrue(t is not None)

if __name__=="__main__":
  if len(sys.argv)==1:
    unittest.main()
