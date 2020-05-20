import universe
reload(universe)
from universe import *

import parameters_fisher
reload(parameters_fisher)
from parameters_fisher import *

import projection_kernel
reload(projection_kernel)
from projection_kernel import *

import pn_2d
reload(pn_2d)
from pn_2d import *

import covp_2d
reload(covp_2d)
from covp_2d import *


##################################################################################

class FisherLsst(object):
   
   def __init__(self, cosmoPar, galaxyBiasPar, shearMultBiasPar, dndzPar, nBins=2, nL=20, fsky=1., magBias=False, fullCross=True, name=None, nProc=3, save=True):
      self.save = save
      self.nProc = nProc
      
      # sky fraction
      self.fsky = fsky
      
      # ell bins
      self.nL = nL
      self.lMin = 20.
      self.lMax = 1.e3
#      self.Le = np.logspace(np.log10(self.lMin), np.log10(self.lMax), self.nL+1, 10.)
#      self.dL = self.Le[1:] - self.Le[:-1]
#      # use the average ell in the bin, weighted by number of modes, as bin center
#      f = lambda i: 2./3. * (self.Le[i+1]**3 - self.Le[i]**3) / (self.Le[i+1]**2 - self.Le[i]**2)
#      self.L = np.array(map(f, range(self.nL)))
      self.L, self.dL, self.Nmodes, self.Le = generateEllBins(self.lMin, self.lMax, self.nL, self.fsky)
      
      # number of bins
      self.nBins = nBins
      self.nG = self.nBins
      self.nS = self.nBins
      if fullCross:
         self.nGG = self.nG * (self.nG+1) / 2   # not just gg from same z-bin
         self.nGS = self.nG * self.nS # not just higher z s than g
      else:
         self.nGG = self.nG   # just gg from same z-bin
         self.nGS = self.nG * (self.nG+1) / 2 # just higher z s than g
      self.nSS = self.nS * (self.nS+1) / 2
      self.n2pt = self.nGG + self.nGS + self.nSS
      print "Tomographic bins: "+str(self.nBins)
      print "2-pt functions: "+str(self.n2pt)
      
      # size of data vector
      self.nData = (self.nGG + self.nGS + self.nSS) * self.nL
      print "Data vector has "+str(self.nData)+" elements"

      # include known magnification bias or not
      self.magBias = magBias
      
      # include null crosses
      self.fullCross = fullCross
      
      # Improving the conditioning of the cov matrix
      # Relative unit for shear
      self.sUnit = 20.
      # ell scaling so that ell^alpha * C_ell is relatively independent of ell
      self.alpha = 1.

      
      # output file names
      self.name = "lsst_gg_gs_ss_nBins"+str(self.nBins)+"_nL"+str(self.nL)
      if self.magBias:
         self.name += "_magbias"
      if fullCross:
         self.name += "_fullcross"
      if name is not None:
         self.name += "_"+name
      print "Ouput file name:", self.name
      
      # create folder for figures
      self.figurePath = "./figures/"+self.name
      if not os.path.exists(self.figurePath):
         os.makedirs(self.figurePath)
      print "Figures folder:", self.figurePath




      ##################################################################################

      # cosmology parameters
      self.cosmoPar = cosmoPar
      
      # nuisance parameters
      self.galaxyBiasPar = galaxyBiasPar
      self.shearMultBiasPar = shearMultBiasPar
      self.dndzPar = dndzPar
      # combined nuisance parameters
      self.nuisancePar = self.galaxyBiasPar.copy()
      self.nuisancePar.addParams(self.shearMultBiasPar)
      self.nuisancePar.addParams(self.dndzPar)
      
      # all parameters
      self.fullPar = self.cosmoPar.copy()
      self.fullPar.addParams(self.nuisancePar)
      print "Params: "+str(self.fullPar.nPar)+" total = "+str(self.cosmoPar.nPar)+" cosmo + "+str(self.nuisancePar.nPar)+" nuisance"

      ##################################################################################
      # Fiducial data vector and covariance
      
      tStartFisher = time()
      
      print "Run CLASS",
      tStart = time()
      self.u = Universe(self.cosmoPar.paramsClassy)
      tStop = time()
      print "("+str(np.round(tStop-tStart,1))+" sec)"

      print "Tracer and shear bins",
      tStart = time()
      self.w_g, self.w_s, self.zBounds = self.generateBins(self.u, self.nuisancePar.fiducial)
      tStop = time()
      print "("+str(np.round(tStop-tStart,1))+" sec)"
      
      print "Power spectra",
      tStart = time()
      self.p2d_gg, self.p2d_gs, self.p2d_ss = self.generatePowerSpectra(self.u, self.w_g, self.w_s, save=self.save)
      tStop = time()
      print "("+str(np.round(tStop-tStart,1))+" sec)"

      print "Data vector",
      tStart = time()
      self.dataVector = self.generateDataVector(self.p2d_gg, self.p2d_gs, self.p2d_ss)
      tStop = time()
      print "("+str(np.round(tStop-tStart,1))+" sec)"

      print "Covariance matrix",
      tStart = time()
      self.covMat = self.generateCov(self.p2d_gg, self.p2d_gs, self.p2d_ss)
      self.invCov = np.linalg.inv(self.covMat)
#      self.invCov = invertMatrixSvdTruncated(self.covMat, epsilon=1.e-8, keepLow=True)
      tStop = time()
      print "("+str(np.round(tStop-tStart,1))+" sec)"
      
      print "Derivatives of the data vector"
      if self.save:
         self.saveDerivativeDataVector()
      self.loadDerivativeDataVector()
      
      print "Fisher matrix"
      tStart = time()
      self.loadFisher()
      tStop = time()
      print "("+str(np.round(tStop-tStart,1))+" sec)"

      tStopFisher = time()
      print "Full calculation took "+str(np.round((tStopFisher-tStartFisher)/60.,1))+" min"

   
   ##################################################################################

   def generateBins(self, u, nuisancePar, save=True):
      # split the nuisance parameters
      galaxyBiasPar = nuisancePar[:self.galaxyBiasPar.nPar]
      shearMultBiasPar = nuisancePar[self.galaxyBiasPar.nPar:self.galaxyBiasPar.nPar+self.shearMultBiasPar.nPar]
      dndzPar = nuisancePar[self.galaxyBiasPar.nPar+self.shearMultBiasPar.nPar:]
      # LSST source sample
      w_glsst = WeightTracerLSSTSources(u, name='glsst')
      # split it into bins
      zBounds = w_glsst.splitBins(self.nBins)
      
      # generate the corresponding tracer and shear bins
      w_g = np.empty(self.nBins, dtype=object)
      w_s = np.empty(self.nBins, dtype=object)
      for iBin in range(self.nBins):
         # sharp photo-z cuts
         zMinP = zBounds[iBin]
         zMaxP = zBounds[iBin+1]
         # photo-z bias and uncertainty for this bin:
#!!!! I am using a loose mean redshift
         dz = 0.  #photoZPar[iBin]
         sz = 0.05 * (1.+0.5*(zMinP+zMaxP))   #photoZPar[self.nBins+iBin] * (1.+0.5*(zMinP+zMaxP))
         
         # true z bounds: truncate at 5 sigma
         # careful for the first and last bin
         zMin = max(zMinP - 5.*sz, 1./w_glsst.aMax-1.)   # 1./w_glsst.aMax-1.
         zMax = min(zMaxP + 5.*sz, 1./w_glsst.aMin-1.)   # 1./w_glsst.aMin-1.
         
#         tStart = time()
         # true dn/dz_true from dn/dz_phot
         p_z_given_zp = lambda zp,z: np.exp(-0.5*(z-zp-dz)**2/sz**2) / np.sqrt(2.*np.pi*sz**2)
         f = lambda zp,z: w_glsst.dndz(zp) * p_z_given_zp(zp,z)
         dndz_tForInterp = lambda z: integrate.quad(f, zMinP, zMaxP, args=(z), epsabs=0., epsrel=1.e-3)[0]

         # additive contribution from outliers
         Zoutliers = np.linspace(1./w_glsst.aMax-1., 1./w_glsst.aMin-1., self.dndzPar.nZ)
         Doutliers = dndzPar[iBin*self.dndzPar.nZ:(iBin+1)*self.dndzPar.nZ]
         dndz_outliers = interp1d(Zoutliers, Doutliers, kind='linear', bounds_error=False, fill_value=0.)
         
         # interpolate it for speed (for lensing kernel calculation)
         Z = np.linspace(zMin, zMax, 101)
         F = np.array(map(dndz_tForInterp, Z))  # true z dist, given Gaussian photo-z
         F += np.array(map(dndz_outliers, Z))  # add the outlier correction
         dndz_t = interp1d(Z, F, kind='linear', bounds_error=False, fill_value=0.)


#         tStop = time()
#         print "-- dndz_t took", tStop-tStart, "sec"


#!!!!!!!!! Bottleneck is clearly the shear bin, by a factor 100 compared to lens bin and getting dndz_t
#         tStart = time()
         # shear bin
         w_s[iBin] = WeightLensCustom(u,
                                      dndz_t, # dn/dz_true
                                      m=lambda z: shearMultBiasPar[iBin], # multiplicative shear bias
                                      zMinG=zMin,
                                      zMaxG=zMax,
                                      name='s'+str(iBin))
#         tStop = time()
#         print "-- shear bin took", tStop-tStart, "sec"


#         tStart = time()
         # tracer bin
         w_g[iBin] = WeightTracerCustom(u,
                                        lambda z: galaxyBiasPar[iBin] * w_glsst.b(z), # galaxy bias
                                        dndz_t, # dn/dz_true
                                        zMin=zMin,
                                        zMax=zMax,
                                        name='g'+str(iBin))
#         tStop = time()
#         print "-- clustering bin took", tStop-tStart, "sec"

         
         # add magnification bias, if requested
         if self.magBias:
   #!!!! I am using a loose mean redshift
            alpha = w_glsst.magnificationBias(0.5*(zMinP+zMaxP))
            print "bin "+str(iBin)+": mag bias alpha="+str(alpha)
            w_g_nomagbias[iBin] = WeightTracerCustom(u,
                                           lambda z: galaxyBiasPar[iBin] * w_glsst.b(z), # galaxy bias
                                           dndz_t, # dn/dz_true
                                           zMin=zMin,
                                           zMax=zMax,
                                           name='g'+str(iBin))
            w_g[iBin].f = lambda a: w_g_nomagbias[iBin].f(a) + 2.*(alpha-1.)*w_s[iBin].f(a)


         #print "- done "+str(iBin+1)+" of "+str(self.nBins)
      #print "total ngal="+str(np.sum([w_g[i].ngal_per_arcmin2 for i in range(self.nBins)]))+"/arcmin2, should be "+str(w_glsst.ngal_per_arcmin2)
      return w_g, w_s, zBounds


   ##################################################################################

   def generatePowerSpectra(self, u, w_g, w_s, name=None, save=True):
      if name is None:
         name = "_"+self.name
      # gg: do not impose same bin
      p2d_gg = np.empty((self.nBins, self.nBins), dtype=object)
      for iBin1 in range(self.nBins):
         # auto-correlation: same bin
         p2d_gg[iBin1, iBin1] = P2d(u, u, w_g[iBin1], fPnoise=lambda l:1./w_g[iBin1].ngal, doT=False, name=name, L=self.L, nProc=1, save=save)
         # cross-correlation: different bins
         for iBin2 in range(iBin1+1, self.nBins):
            p2d_gg[iBin1, iBin2] = P2d(u, u, w_g[iBin1], w_g[iBin2], doT=False, name=name, L=self.L, nProc=1, save=save)
            # so that the order doesn't matter
            p2d_gg[iBin2, iBin1] = p2d_gg[iBin1, iBin2]

      # gs: do not impose higher z s than g
      p2d_gs = np.empty((self.nBins, self.nBins), dtype=object)
      for iBin1 in range(self.nBins):
         for iBin2 in range(self.nBins):
            p2d_gs[iBin1, iBin2] = P2d(u, u, w_g[iBin1], w_s[iBin2], doT=False, name=name, L=self.L, nProc=1, save=save)
      
      # ss
      p2d_ss = np.empty((self.nBins, self.nBins), dtype=object)
      for iBin1 in range(self.nBins):
         # auto-correlation: same bin
         p2d_ss[iBin1, iBin1] = P2d(u, u, w_s[iBin1], fPnoise=lambda l:0.26**2/w_s[iBin1].ngal, doT=False, name=name, L=self.L, nProc=1, save=save)
         # cross correlation: different bins
         for iBin2 in range(iBin1+1, self.nBins):
            p2d_ss[iBin1, iBin2] = P2d(u, u, w_s[iBin1], w_s[iBin2], doT=False, name=name, L=self.L, nProc=1, save=save)
            # so that the order doesn't matter
            p2d_ss[iBin2, iBin1] = p2d_ss[iBin1, iBin2]

      return p2d_gg, p2d_gs, p2d_ss


   ##################################################################################

   def generateDataVector(self, p2d_gg, p2d_gs, p2d_ss):
      '''The data vector is made of the various power spectra,
      with a choice of units that makes the covariance matrix for gg and ss more similar,
      and with an ell^alpha factor that makes the covariance matrix more ell-independent.
      '''
      dataVector = np.zeros(self.nData)
      iData = 0
      # gg
      for iBin1 in range(self.nBins):
         for iBin2 in range(iBin1, self.nBins):
            if (iBin2==iBin1) or self.fullCross:
               dataVector[iData*self.nL:(iData+1)*self.nL] = np.array(map(p2d_gg[iBin1, iBin2].fPinterp, self.L))
               dataVector[iData*self.nL:(iData+1)*self.nL] *= self.L**self.alpha
               iData += 1
      # gs
      for iBin1 in range(self.nBins):
         for iBin2 in range(self.nBins):
            if (iBin2>=iBin1) or self.fullCross:
               dataVector[iData*self.nL:(iData+1)*self.nL] = np.array(map(p2d_gs[iBin1, iBin2].fPinterp, self.L))
               dataVector[iData*self.nL:(iData+1)*self.nL] *= self.sUnit * self.L**self.alpha
               iData += 1
      # ss
      for iBin1 in range(self.nBins):
         for iBin2 in range(iBin1, self.nBins):
            dataVector[iData*self.nL:(iData+1)*self.nL] = np.array(map(p2d_ss[iBin1, iBin2].fPinterp, self.L))
            dataVector[iData*self.nL:(iData+1)*self.nL] *= self.sUnit**2 * self.L**self.alpha
            iData += 1
      
      return dataVector


   ##################################################################################

   def generateCov(self, p2d_gg, p2d_gs, p2d_ss):
      covMat = np.zeros((self.nData, self.nData))
      # below, i1 and i2 define the row and column of the nL*nL blocks for each pair of 2-point function
      # i1, i2 \in [0, nGG+nGS+nSS]
      
      #print "gg-gg"
      # considering gg[i1,i2]
      i1 = 0
      for iBin1 in range(self.nBins):
         for iBin2 in range(iBin1, self.nBins):
            if (iBin2==iBin1) or self.fullCross:
               # considering gg[j1,j2]
               i2 = 0
               for jBin1 in range(self.nBins):
                  for jBin2 in range(jBin1, self.nBins):
                     if (jBin2==jBin1) or self.fullCross:
                        # compute only upper diagonal
                        if i2>=i1:
                           covBlock = CovP2d(p2d_gg[iBin1,jBin1], p2d_gg[iBin2,jBin2], p2d_gg[iBin1,jBin2], p2d_gg[iBin2,jBin1], self.Nmodes)
                           covMat[i1*self.nL:(i1+1)*self.nL, i2*self.nL:(i2+1)*self.nL] = self.L**(2*self.alpha) * covBlock.covMat
                        # move to next column
                        i2 += 1
               # move to next row
               i1 += 1

      #print "gg-gs"
      # considering gg[i1,i2]
      i1 = 0
      for iBin1 in range(self.nBins):
         for iBin2 in range(iBin1, self.nBins):
            if (iBin2==iBin1) or self.fullCross:
               # considering gs[j1,j2]
               i2 = self.nGG
               for jBin1 in range(self.nBins):
                  for jBin2 in range(self.nBins):
                     if (jBin2>=jBin1) or self.fullCross:
                        # compute only upper diagonal
                        if i2>=i1:
                           covBlock = CovP2d(p2d_gg[iBin1,jBin1], p2d_gs[iBin2,jBin2], p2d_gs[iBin1,jBin2], p2d_gg[iBin2,jBin1], self.Nmodes)
                           covMat[i1*self.nL:(i1+1)*self.nL, i2*self.nL:(i2+1)*self.nL] = self.sUnit *self.L**(2*self.alpha) *  covBlock.covMat
                        # move to next column
                        i2 += 1
               # move to next row
               i1 += 1

      #print "gg-ss"
      # considering gg[i1,i2]
      i1 = 0
      for iBin1 in range(self.nBins):
         for iBin2 in range(iBin1, self.nBins):
            if (iBin2==iBin1) or self.fullCross:
               # considering ss[j1,j2]
               i2 = self.nGG + self.nGS
               for jBin1 in range(self.nBins):
                  for jBin2 in range(jBin1, self.nBins):
                     # compute only upper diagonal
                     if i2>=i1:
                        covBlock = CovP2d(p2d_gs[iBin1,jBin1], p2d_gs[iBin2,jBin2], p2d_gs[iBin1,jBin2], p2d_gs[iBin2,jBin1], self.Nmodes)
                        covMat[i1*self.nL:(i1+1)*self.nL, i2*self.nL:(i2+1)*self.nL] = self.sUnit**2 * self.L**(2*self.alpha) * covBlock.covMat
                     # move to next column
                     i2 += 1
               # move to next row
               i1 += 1

      #print "gs-gs"
      # considering gs[i1,i2]
      i1 = self.nGG
      for iBin1 in range(self.nBins):
         for iBin2 in range(self.nBins):
            if (iBin2>=iBin1) or self.fullCross:
               # considering gs[j1,j2]
               i2 = self.nGG
               for jBin1 in range(self.nBins):
                  for jBin2 in range(self.nBins):
                     if (jBin2>=jBin1) or self.fullCross:
                        # compute only upper diagonal
                        if i2>=i1:
                           # watch the order for gs
                           covBlock = CovP2d(p2d_gg[iBin1,jBin1], p2d_ss[iBin2,jBin2], p2d_gs[iBin1,jBin2], p2d_gs[jBin1,iBin2], self.Nmodes)
                           covMat[i1*self.nL:(i1+1)*self.nL, i2*self.nL:(i2+1)*self.nL] = self.sUnit**2 * self.L**(2*self.alpha) * covBlock.covMat
                        # move to next column
                        i2 += 1
               # move to next row
               i1 += 1

      #print "gs-ss"
      # considering gs[i1,i2]
      i1 = self.nGG
      for iBin1 in range(self.nBins):
         for iBin2 in range(self.nBins):
            if (iBin2>=iBin1) or self.fullCross:
               # considering ss[j1,j2]
               i2 = self.nGG + self.nGS
               for jBin1 in range(self.nBins):
                  for jBin2 in range(jBin1, self.nBins):
                     # compute only upper diagonal
                     if i2>=i1:
                        covBlock = CovP2d(p2d_gs[iBin1,jBin1], p2d_ss[iBin2,jBin2], p2d_gs[iBin1,jBin2], p2d_ss[iBin2,jBin1], self.Nmodes)
                        covMat[i1*self.nL:(i1+1)*self.nL, i2*self.nL:(i2+1)*self.nL] = self.sUnit**3 * self.L**(2*self.alpha) * covBlock.covMat
                     # move to next column
                     i2 += 1
               # move to next row
               i1 += 1

      #print "ss-ss"
      # considering ss[i1,i2]
      i1 = self.nGG + self.nGS
      for iBin1 in range(self.nBins):
         for iBin2 in range(iBin1, self.nBins):
            # considering ss[j1,j2]
            i2 = self.nGG + self.nGS
            for jBin1 in range(self.nBins):
               for jBin2 in range(jBin1, self.nBins):
                  # compute only upper diagonal
                  if i2>=i1:
                     covBlock = CovP2d(p2d_ss[iBin1,jBin1], p2d_ss[iBin2,jBin2], p2d_ss[iBin1,jBin2], p2d_ss[iBin2,jBin1], self.Nmodes)
                     covMat[i1*self.nL:(i1+1)*self.nL, i2*self.nL:(i2+1)*self.nL] = self.sUnit**4 * self.L**(2*self.alpha) * covBlock.covMat
                  # move to next column
                  i2 += 1
            # move to next row
            i1 += 1

      # fill lower diagonal by symmetry
      # here i1 and i2 don't index the matrix blocks, but the matrix elements
      for i1 in range(self.nData):
         for i2 in range(i1):
            covMat[i1, i2] = covMat[i2, i1]

      return covMat


   ##################################################################################
   
   def printSnrPowerSpectra(self, path):
      if not self.fullCross:
         print "(function only implemented for fullCross)"
         return
      with open(path, 'w') as f:
         f.write("SNR\n\n")
         
         ###########################################################
         # gg
         
         # gg: auto
         f.write("GG\n")
         f.write("auto\n")
         i1 = 0
         Itotal = []
         for iBin1 in range(self.nBins):
            I = range(i1*self.nL, (i1+1)*self.nL)
            d = self.dataVector[I]
            J = np.ix_(I,I)
            cov = self.covMat[J]
            invCov = np.linalg.inv(cov)
            snr = np.dot(d.transpose(), np.dot(invCov, d))
            snr = np.sqrt(snr)
            f.write("   "+str(iBin1)+","+str(iBin1)+": "+str(snr)+"\n")
            i1 += self.nBins - iBin1
            Itotal += I
         # gg: total auto
         d = self.dataVector[Itotal]
         J = np.ix_(Itotal,Itotal)
         cov = self.covMat[J]
         invCov = np.linalg.inv(cov)
         snr = np.dot(d.transpose(), np.dot(invCov, d))
         snr = np.sqrt(snr)
         f.write("total auto: "+str(snr)+"\n")
         
         
         # gg: cross i,i+1
         f.write("cross i,i+1\n")
         i1 = 1
         Itotal = []
         for iBin1 in range(self.nBins-1):
            I = range(i1*self.nL, (i1+1)*self.nL)
            d = self.dataVector[I]
            J = np.ix_(I,I)
            cov = self.covMat[J]
            invCov = np.linalg.inv(cov)
            snr = np.dot(d.transpose(), np.dot(invCov, d))
            snr = np.sqrt(snr)
            f.write("   "+str(iBin1)+","+str(iBin1+i1)+": "+str(snr)+"\n")
            i1 += self.nBins - iBin1
            Itotal += I
         # gg: total i,i+1
         d = self.dataVector[Itotal]
         J = np.ix_(Itotal,Itotal)
         cov = self.covMat[J]
         invCov = np.linalg.inv(cov)
         snr = np.dot(d.transpose(), np.dot(invCov, d))
         snr = np.sqrt(snr)
         f.write("total i,i+1: "+str(snr)+"\n")


         # gg: cross i,i+2
         f.write("cross i,i+2\n")
         i1 = 2
         Itotal = []
         for iBin1 in range(self.nBins-2):
            I = range(i1*self.nL, (i1+1)*self.nL)
            d = self.dataVector[I]
            J = np.ix_(I,I)
            cov = self.covMat[J]
            invCov = np.linalg.inv(cov)
            snr = np.dot(d.transpose(), np.dot(invCov, d))
            snr = np.sqrt(snr)
            f.write("   "+str(iBin1)+","+str(iBin1+i1)+": "+str(snr)+"\n")
            i1 += self.nBins - iBin1
            Itotal += I
         # gg: total i,i+2
         d = self.dataVector[Itotal]
         J = np.ix_(Itotal,Itotal)
         cov = self.covMat[J]
         invCov = np.linalg.inv(cov)
         snr = np.dot(d.transpose(), np.dot(invCov, d))
         snr = np.sqrt(snr)
         f.write("total i,i+2: "+str(snr)+"\n")
         
         # gg: all
         f.write("all\n")
         i1 = 0
         for iBin1 in range(self.nBins):
            for iBin2 in range(self.nBins):
               I = range(i1*self.nL, (i1+1)*self.nL)
               d = self.dataVector[I]
               J = np.ix_(I,I)
               cov = self.covMat[J]
               invCov = np.linalg.inv(cov)
               snr = np.dot(d.transpose(), np.dot(invCov, d))
               snr = np.sqrt(snr)
               f.write("   "+str(iBin1)+","+str(iBin2)+": "+str(snr)+"\n")
               i1 += 1
         # gg: total
         I = range(self.nGG*self.nL)
         d = self.dataVector[I]
         J = np.ix_(I,I)
         cov = self.covMat[J]
         invCov = np.linalg.inv(cov)
         snr = np.dot(d.transpose(), np.dot(invCov, d))
         snr = np.sqrt(snr)
         f.write("total gg: "+str(snr)+"\n\n")

         ###########################################################
         # gs

         # gs: all
         f.write("GS\n")
         f.write("all\n")
         i1 = self.nGG
         for iBin1 in range(self.nBins):
            for iBin2 in range(self.nBins):
               I = range(i1*self.nL, (i1+1)*self.nL)
               d = self.dataVector[I]
               J = np.ix_(I,I)
               cov = self.covMat[J]
               invCov = np.linalg.inv(cov)
               snr = np.dot(d.transpose(), np.dot(invCov, d))
               snr = np.sqrt(snr)
               f.write("   "+str(iBin1)+","+str(iBin2)+": "+str(snr)+"\n")
               i1 += 1
         # gs: total
         I = range(self.nGG*self.nL, (self.nGG+self.nGS)*self.nL)
         d = self.dataVector[I]
         J = np.ix_(I,I)
         cov = self.covMat[J]
         invCov = np.linalg.inv(cov)
         snr = np.dot(d.transpose(), np.dot(invCov, d))
         snr = np.sqrt(snr)
         f.write("total gs: "+str(snr)+"\n\n")

         ###########################################################
         # ss
         
         f.write("SS\n")
         
         # ss: auto
         f.write("auto\n")
         i1 = self.nGG + self.nGS
         Itotal = []
         for iBin1 in range(self.nBins):
            I = range(i1*self.nL, (i1+1)*self.nL)
            d = self.dataVector[I]
            J = np.ix_(I,I)
            cov = self.covMat[J]
            invCov = np.linalg.inv(cov)
            snr = np.dot(d.transpose(), np.dot(invCov, d))
            snr = np.sqrt(snr)
            f.write("   "+str(iBin1)+","+str(iBin1)+": "+str(snr)+"\n")
            i1 += self.nBins - iBin1
            Itotal += I
         # ss: total auto
         d = self.dataVector[Itotal]
         J = np.ix_(Itotal,Itotal)
         cov = self.covMat[J]
         invCov = np.linalg.inv(cov)
         snr = np.dot(d.transpose(), np.dot(invCov, d))
         snr = np.sqrt(snr)
         f.write("total auto: "+str(snr)+"\n")

         # ss: all
         f.write("all\n")
         i1 = self.nGG + self.nGS
         for iBin1 in range(self.nBins):
            for iBin2 in range(iBin1, self.nBins):
               I = range(i1*self.nL, (i1+1)*self.nL)
               d = self.dataVector[I]
               J = np.ix_(I,I)
               cov = self.covMat[J]
               invCov = np.linalg.inv(cov)
               snr = np.dot(d.transpose(), np.dot(invCov, d))
               snr = np.sqrt(snr)
               f.write("   "+str(iBin1)+","+str(iBin2)+": "+str(snr)+"\n")
               i1 += 1
         # ss: total
         I = range((self.nGG+self.nGS)*self.nL, (self.nGG+self.nGS+self.nSS)*self.nL)
         d = self.dataVector[I]
         J = np.ix_(I,I)
         cov = self.covMat[J]
         invCov = np.linalg.inv(cov)
         snr = np.dot(d.transpose(), np.dot(invCov, d))
         snr = np.sqrt(snr)
         f.write("total ss: "+str(snr)+"\n\n")

         ###########################################################
         # gg, gs, ss

         snr = np.dot(self.dataVector.transpose(), np.dot(self.invCov, self.dataVector))
         snr = np.sqrt(snr)
         f.write("total gg, gs, ss: "+str(snr)+"\n\n")


   
   ##################################################################################

   def saveDerivativeDataVector(self):
      # Derivatives of the data vector:
      # matrix of size self.params.nPar x self.nData
      derivative = np.zeros((self.fullPar.nPar, self.nData))
      
      for iPar in range(self.cosmoPar.nPar):
         print "Derivative wrt "+self.cosmoPar.names[iPar],
         tStart = time()
         # high
         name = self.name+self.cosmoPar.names[iPar]+"high"
         cosmoParClassy = self.cosmoPar.paramsClassy.copy()
#         print cosmoParClassy
#         print "#"
         cosmoParClassy[self.cosmoPar.names[iPar]] = self.cosmoPar.paramsClassyHigh[self.cosmoPar.names[iPar]]
#         print cosmoParClassy
         u = Universe(cosmoParClassy)
         w_g, w_s, zBounds = self.generateBins(u, self.nuisancePar.fiducial)
         p2d_gg, p2d_gs, p2d_ss = self.generatePowerSpectra(u, w_g, w_s, name=name, save=True)
         dataVectorHigh = self.generateDataVector(p2d_gg, p2d_gs, p2d_ss)
         # low
         name = self.name+self.cosmoPar.names[iPar]+"low"
         cosmoParClassy = self.cosmoPar.paramsClassy.copy()
         cosmoParClassy[self.cosmoPar.names[iPar]] = self.cosmoPar.paramsClassyLow[self.cosmoPar.names[iPar]]
         u = Universe(cosmoParClassy)
         w_g, w_s, zBounds = self.generateBins(u, self.nuisancePar.fiducial)
         p2d_gg, p2d_gs, p2d_ss = self.generatePowerSpectra(u, w_g, w_s, name=name, save=True)
         dataVectorLow = self.generateDataVector(p2d_gg, p2d_gs, p2d_ss)
         # derivative
         derivative[iPar,:] = (dataVectorHigh-dataVectorLow) / (self.cosmoPar.high[iPar]-self.cosmoPar.low[iPar])
#         derivative[iPar,:] = (dataVectorHigh-self.dataVector) / (self.cosmoPar.high[iPar]-self.cosmoPar.fiducial[iPar])

#         print "all zero?"
#         print np.mean(dataVectorHigh-self.dataVector) / np.std(self.dataVector)
#         print self.cosmoPar.high[iPar]-self.cosmoPar.fiducial[iPar]

         # check that all went well
         if not all(np.isfinite(derivative[iPar,:])):
            print "########"
            print "problem with "+self.cosmoPar.names[iPar]
            print "high value = "+str(self.cosmoPar.high[iPar])
            print "low value = "+str(self.cosmoPar.fiducial[iPar])
         tStop = time()
         print "("+str(np.round(tStop-tStart,1))+" sec)"
      
      
      # Nuisance parameters
      for iPar in range(self.nuisancePar.nPar):
         print "Derivative wrt "+self.nuisancePar.names[iPar],
         tStart = time()
         params = self.nuisancePar.fiducial.copy()
         # high
         name = "_"+self.name+self.nuisancePar.names[iPar]+"high"
         params[iPar] = self.nuisancePar.high[iPar]
         w_g, w_s, zBounds = self.generateBins(self.u, params)
         p2d_gg, p2d_gs, p2d_ss = self.generatePowerSpectra(self.u, w_g, w_s, name=name, save=True)
         dataVectorHigh = self.generateDataVector(p2d_gg, p2d_gs, p2d_ss)
         # low
         name = self.name+self.nuisancePar.names[iPar]+"low"
         params[iPar] = self.nuisancePar.low[iPar]
         w_g, w_s, zBounds = self.generateBins(self.u, params)
         p2d_gg, p2d_gs, p2d_ss = self.generatePowerSpectra(self.u, w_g, w_s, name=name, save=True)
         dataVectorLow = self.generateDataVector(p2d_gg, p2d_gs, p2d_ss)
         # derivative
         derivative[self.cosmoPar.nPar+iPar,:] = (dataVectorHigh-dataVectorLow) / (self.nuisancePar.high[iPar]-self.nuisancePar.low[iPar])
#         derivative[self.cosmoPar.nPar+iPar,:] = (dataVectorHigh-self.dataVector) / (self.nuisancePar.high[iPar]-self.nuisancePar.fiducial[iPar])
         # check that all went well
         if not all(np.isfinite(derivative[self.cosmoPar.nPar+iPar,:])):
            print "########"
            print "problem with "+self.nuisancePar.names[iPar]
            print "high value = "+str(self.nuisancePar.high[iPar])
            print "low value = "+str(self.nuisancePar.fiducial[iPar])
         
         tStop = time()
         print "("+str(np.round(tStop-tStart,1))+" sec)"
      
      path = "./output/dDatadPar/dDatadPar_"+self.name
      np.savetxt(path, derivative)

   def loadDerivativeDataVector(self):
      path = "./output/dDatadPar/dDatadPar_"+self.name
      self.derivativeDataVector = np.genfromtxt(path)


   ##################################################################################
   
   def loadFisher(self):
      self.fisherData = np.zeros((self.fullPar.nPar, self.fullPar.nPar))
      # Fisher from the data
      for i in range(self.fullPar.nPar):
         for j in range(self.fullPar.nPar):
            result = np.dot(self.invCov, self.derivativeDataVector[j,:])
            result = np.dot(self.derivativeDataVector[i,:].transpose(), result)
            self.fisherData[i,j] = result
      # Fisher from the prior
      self.fisherPrior = self.fullPar.fisher.copy()
      # Fisher from data and prior
      self.fisherPosterior = self.fisherData + self.fisherPrior
      # create posterior parameter object
      self.posteriorPar = self.fullPar.copy()
      self.posteriorPar.fisher = self.fisherPosterior.copy()
   

   ##################################################################################
   ##################################################################################
   
   def checkConditionNumbers(self):
      print "Cov matrix"
      print "inverse condition number:", 1./np.linalg.cond(self.covMat)
      print "number numerical precision:", np.finfo(self.covMat.dtype).eps
      if 1./np.linalg.cond(self.covMat) > np.finfo(self.covMat.dtype).eps:
         print "--> OK"
      else:
         print "--> Not OK"
      #
      print "Fisher matrix"
      print "inverse condition number:", 1./np.linalg.cond(self.fisherPosterior)
      print "number numerical precision:", np.finfo(self.fisherPosterior.dtype).eps
      if 1./np.linalg.cond(self.fisherPosterior) > np.finfo(self.fisherPosterior.dtype).eps:
         print "--> OK"
      else:
         print "--> Not OK"

   
   def plotDndz(self):
      fig=plt.figure(0)
      ax=fig.add_subplot(111)
      #
      # full LSST source sample
      w_glsst = WeightTracerLSSTSources(self.u, name='glsst')
      zMin = 1./w_glsst.aMax-1.
      zMax = 1./w_glsst.aMin-1.
      Z = np.linspace(zMin, zMax, 501)
      dndz = w_glsst.dndz(Z)
      dndz /= (180.*60./np.pi)**2 # convert from 1/sr to 1/arcmin^2
      ax.plot(Z, dndz, 'k')
      #
      # binned with photo-z uncertainties
      for iBin in range(self.nBins):
         # redshift range for that bin
         zMin = 1./self.w_g[iBin].aMax-1.
         zMax = 1./self.w_g[iBin].aMin-1.
         Z = np.linspace(zMin, zMax, 501)
         # evaluate dn/dz
         dndz = np.array(map(self.w_g[iBin].dndz, Z))
         dndz /= (180.*60./np.pi)**2 # convert from 1/sr to 1/arcmin^2
         # plot it
         ax.fill_between(Z, 0., dndz, facecolor=plt.cm.autumn(1.*iBin/self.nBins), edgecolor='', alpha=0.7)
      #
      ax.set_xlabel(r'$z$')
      ax.set_ylabel(r'$dN / d\Omega\; dz$ [arcmin$^{-2}$]')
      #
      fig.savefig(self.figurePath+"/dndz.pdf")
      fig.clf()

   
   
   def plotCovMat(self):
      fig=plt.figure(0, figsize=(12,8))
      ax=fig.add_subplot(111)
      #
      # compute correlation matrix
      corMat = np.zeros_like(self.covMat)
      for i in range(self.nData):
         for j in range(self.nData):
            corMat[i,j] = self.covMat[i,j] / np.sqrt(self.covMat[i,i] * self.covMat[j,j])
      upperDiag = np.triu(np.ones(self.nData))
      plt.imshow(corMat * upperDiag, interpolation='nearest', norm=LogNorm(vmin=1.e-4, vmax=1), cmap=cmaps.viridis_r)
      #
      ax.plot(np.arange(self.nData+1)-0.5, np.arange(self.nData+1)-0.5, 'k', lw=1)
      #
      # 2-pt function delimiters
      for i in range(1, self.nGG+self.nGS+self.nSS):
         ax.axhline(self.nL*i-0.5, xmin=(self.nL*i-0.5)/self.nData, c='gray', lw=0.25, ls='-')
         ax.axvline(self.nL*i-0.5, ymin=1.-(self.nL*i-0.5)/self.nData, c='gray', lw=0.25, ls='-')
      #
      # block delimiters
      ax.axhline(self.nL*self.nGG-0.5, xmin=(self.nL*self.nGG-0.5)/self.nData, c='k', lw=1.5)
      ax.axhline(self.nL*(self.nGG+self.nGS)-0.5, xmin=(self.nL*(self.nGG+self.nGS)-0.5)/self.nData, c='k', lw=1.5)
      #
      ax.axvline(self.nL*self.nGG-0.5, ymin=1.-(self.nL*self.nGG-0.5)/self.nData, c='k', lw=1.5)
      ax.axvline(self.nL*(self.nGG+self.nGS)-0.5, ymin=1.-(self.nL*(self.nGG+self.nGS)-0.5)/self.nData, c='k', lw=1.5)
      #
      plt.colorbar()
      ax.set_xlim((-0.5, (self.nData-1)+0.5))
      ax.set_ylim((-0.5, (self.nData-1)+0.5))
      ax.invert_yaxis()
      #ax.xaxis.tick_top()
      ax.xaxis.set_ticks([])
      ax.yaxis.set_ticks([])
      #ax.grid(True)
      #ax.set_title(r'Full cor: '+infile)
      #
      fig.savefig(self.figurePath+"/cor_mat.pdf", bbox_inches='tight', format='pdf', dpi=2400)
      fig.clf()


   def plotInvCovMat(self):
      fig=plt.figure(0, figsize=(12,8))
      ax=fig.add_subplot(111)
      #
      upperDiag = np.triu(np.ones(self.nData))
#      plt.imshow(self.invCov * upperDiag, interpolation='nearest', norm=LogNorm(vmin=1.e-4, vmax=1), cmap=cmaps.viridis_r)
      plt.imshow(np.abs(self.invCov) * upperDiag, interpolation='nearest', norm=LogNorm(), cmap=cmaps.bwr)
      #
      ax.plot(np.arange(self.nData+1)-0.5, np.arange(self.nData+1)-0.5, 'k', lw=1)
      #
      # 2-pt function delimiters
      for i in range(1, self.nGG+self.nGS+self.nSS):
         ax.axhline(self.nL*i-0.5, xmin=(self.nL*i-0.5)/self.nData, c='gray', lw=0.25, ls='-')
         ax.axvline(self.nL*i-0.5, ymin=1.-(self.nL*i-0.5)/self.nData, c='gray', lw=0.25, ls='-')
      #
      # block delimiters
      ax.axhline(self.nL*self.nGG-0.5, xmin=(self.nL*self.nGG-0.5)/self.nData, c='k', lw=1.5)
      ax.axhline(self.nL*(self.nGG+self.nGS)-0.5, xmin=(self.nL*(self.nGG+self.nGS)-0.5)/self.nData, c='k', lw=1.5)
      #
      ax.axvline(self.nL*self.nGG-0.5, ymin=1.-(self.nL*self.nGG-0.5)/self.nData, c='k', lw=1.5)
      ax.axvline(self.nL*(self.nGG+self.nGS)-0.5, ymin=1.-(self.nL*(self.nGG+self.nGS)-0.5)/self.nData, c='k', lw=1.5)
      #
      plt.colorbar()
      ax.set_xlim((-0.5, (self.nData-1)+0.5))
      ax.set_ylim((-0.5, (self.nData-1)+0.5))
      ax.invert_yaxis()
      #ax.xaxis.tick_top()
      ax.xaxis.set_ticks([])
      ax.yaxis.set_ticks([])
      #
      fig.savefig(self.figurePath+"/invcov_mat.pdf", bbox_inches='tight', format='pdf', dpi=2400)
      fig.clf()



#   def plotPowerSpectra(self):
#
#      # gg: panels
#      Colors = plt.cm.autumn(1.*np.arange(self.nBins)/(self.nBins-1.))
#      #
#      fig=plt.figure(0)
#      gs = gridspec.GridSpec(3, 1)#, height_ratios=[1, 1, 1])
#      gs.update(hspace=0.)
#
#      # auto
#      ax0=plt.subplot(gs[0])
#      i1 = 0
#      for iBin1 in range(self.nBins):
#         d = self.dataVector[i1*self.nL:(i1+1)*self.nL]
#         std = np.sqrt(np.diag(self.covMat[i1*self.nL:(i1+1)*self.nL, i1*self.nL:(i1+1)*self.nL]))
#         #
#         color = Colors[iBin1]
#         ax0.errorbar(self.L, d, yerr=std, ls='-', lw=2, elinewidth=1.5, marker='.', markersize=2, color=color)
#         # advance counter in data vector
#         i1 += self.nBins - iBin1
#      #
#      ax0.set_xscale('log')
#      ax0.set_yscale('log', nonposy='clip')
#      plt.setp(ax0.get_xticklabels(), visible=False)
#      #
#      ax0.set_title(r'Clustering')
#      ax0.set_ylabel(r'$\langle g_i g_i\rangle$', fontsize=18)
#
#      # cross i,i+1
#      ax1=plt.subplot(gs[1])
#      i1 = 1
#      for iBin1 in range(self.nBins-1):
#         d = self.dataVector[i1*self.nL:(i1+1)*self.nL]
#         std = np.sqrt(np.diag(self.covMat[i1*self.nL:(i1+1)*self.nL, i1*self.nL:(i1+1)*self.nL]))
#         #
#         color = Colors[iBin1]
#         ax1.errorbar(self.L, d, yerr=std, ls='-', lw=2, elinewidth=1.5, marker='.', markersize=2, color=color)
#         # advance counter in data vector
#         i1 += self.nBins - iBin1
#      #
#      ax1.set_xscale('log')
#      ax1.set_yscale('log', nonposy='clip')
#      plt.setp(ax1.get_xticklabels(), visible=False)
#      #
#      ax1.set_ylabel(r'$\langle g_i g_{i+1}\rangle$', fontsize=18)
#
#      # cross i,i+2
#      ax2=plt.subplot(gs[2])
#      i1 = 2
#      for iBin1 in range(self.nBins-2):
#         d = self.dataVector[i1*self.nL:(i1+1)*self.nL]
#         std = np.sqrt(np.diag(self.covMat[i1*self.nL:(i1+1)*self.nL, i1*self.nL:(i1+1)*self.nL]))
#         #
#         color = Colors[iBin1]
#         ax2.errorbar(self.L, d, yerr=std, ls='-', lw=2, elinewidth=1.5, marker='.', markersize=2, color=color)
#         # advance counter in data vector
#         i1 += self.nBins - iBin1
#      #
#      ax2.set_xscale('log')
#      ax2.set_yscale('log', nonposy='clip')
#      #
#      ax2.set_ylabel(r'$\langle g_i g_{i+2}\rangle$', fontsize=18)
#      ax2.set_xlabel(r'$\ell$')
#      #
#      fig.savefig(self.figurePath+"/p2d_gg.pdf")
#      fig.clf()
#
#
#
#      # gs
#      Colors = plt.cm.winter(1.*np.arange(self.nBins)/(self.nBins-1.))
#      fig=plt.figure(1)
#      ax=fig.add_subplot(111)
#      #
#      i1 = self.nGG
#      for iBin1 in range(self.nBins):
#         color = Colors[iBin1]
#         for iBin2 in range(self.nBins):
#            d = self.dataVector[i1*self.nL:(i1+1)*self.nL]
#            std = np.sqrt(np.diag(self.covMat[i1*self.nL:(i1+1)*self.nL, i1*self.nL:(i1+1)*self.nL]))
#            ax.errorbar(self.L*(1.+0.01*i1/self.nGS), d, yerr=std, ls='-', lw=1, elinewidth=1.5, marker='.', markersize=2, color=color)# label=r'$\langle g_{'+str(iBin1)+'} \gamma_{'+str(iBin2)+r'}\rangle$')
#            # move to next row
#            i1 += 1
#      #
#      ax.legend(loc=1)
#      ax.set_xscale('log')
#      ax.set_yscale('log', nonposy='clip')
#      ax.set_xlabel(r'$\ell$')
#      ax.set_ylabel(r'$C_\ell^{g\gamma}$')
#      ax.set_title(r'Galaxy - galaxy lensing')
#      #
#      fig.savefig(self.figurePath+"/p2d_gs.pdf")
#      fig.clf()
#
#
#      # ss: all on same plot
#      Colors = plt.cm.jet(1.*np.arange(self.nBins)/(self.nBins-1.))
#      fig=plt.figure(2)
#      ax=fig.add_subplot(111)
#      #
#      i1 = self.nGG + self.nGS
#      for iBin1 in range(self.nBins):
#         # add entry to caption
#         color = Colors[iBin1]
#         ax.plot([], [], c=color, label=r'$\langle\gamma_{i} \gamma_{i+'+str(iBin1)+r'} \rangle $')
#         for iBin2 in range(iBin1, self.nBins):
#            d = self.dataVector[i1*self.nL:(i1+1)*self.nL]
#            #
#            color = Colors[iBin2-iBin1]
#            #
#            std = np.sqrt(np.diag(self.covMat[i1*self.nL:(i1+1)*self.nL, i1*self.nL:(i1+1)*self.nL]))
#            ax.errorbar(self.L*(1.+0.01*i1/self.nSS), d, yerr=std, ls='-', lw=1, elinewidth=1.5, marker='.', markersize=2, color=color)#, label=r'$\gamma_{'+str(iBin1)+'} \gamma_{'+str(iBin2)+'}$')
#            # move to next row
#            i1 += 1
#      #
#      ax.legend(loc=1, labelspacing=0.05, handlelength=0.4, borderaxespad=0.01)
#      ax.set_xscale('log')
#      ax.set_yscale('log', nonposy='clip')
#      ax.set_xlabel(r'$\ell$')
#      ax.set_ylabel(r'$C_\ell^{\gamma\gamma}$')
#      ax.set_title(r'Shear tomography')
#      #
#      fig.savefig(self.figurePath+"/p2d_ss.pdf")
#      fig.clf()



   def plotPowerSpectra(self):
      if not self.fullCross:
         print "(function only implemented for fullCross)"
         return
      
      # gg: panels
      Colors = plt.cm.autumn(1.*np.arange(self.nBins)/(self.nBins-1.))
      #
      fig=plt.figure(0)
      gs = gridspec.GridSpec(3, 1)#, height_ratios=[1, 1, 1])
      gs.update(hspace=0.)
      
      # auto
      ax0=plt.subplot(gs[0])
      i1 = 0
      for iBin1 in range(self.nBins):
         d = self.L * self.dataVector[i1*self.nL:(i1+1)*self.nL]
         std = self.L * np.sqrt(np.diag(self.covMat[i1*self.nL:(i1+1)*self.nL, i1*self.nL:(i1+1)*self.nL]))
         #
         color = Colors[iBin1]
         ax0.errorbar(self.L, d, yerr=std, ls='-', lw=2, elinewidth=1.5, marker='.', markersize=2, color=color)
         # advance counter in data vector
         i1 += self.nBins - iBin1
      #
      ax0.set_xscale('log')
      ax0.set_yscale('log', nonposy='clip')
      plt.setp(ax0.get_xticklabels(), visible=False)
      #
      ax0.set_title(r'$\ell\; C_\ell^{gg}$')
      ax0.set_ylabel(r'$\langle g_i g_i\rangle$', fontsize=18)

      # cross i,i+1
      ax1=plt.subplot(gs[1])
      i1 = 1
      for iBin1 in range(self.nBins-1):
         d = self.L * self.dataVector[i1*self.nL:(i1+1)*self.nL]
         std = self.L * np.sqrt(np.diag(self.covMat[i1*self.nL:(i1+1)*self.nL, i1*self.nL:(i1+1)*self.nL]))
         #
         color = Colors[iBin1]
         ax1.errorbar(self.L, d, yerr=std, ls='-', lw=2, elinewidth=1.5, marker='.', markersize=2, color=color)
         # advance counter in data vector
         i1 += self.nBins - iBin1
      #
      ax1.set_xscale('log')
      ax1.set_yscale('log', nonposy='clip')
      plt.setp(ax1.get_xticklabels(), visible=False)
      #
      ax1.set_ylabel(r'$\langle g_i g_{i+1}\rangle$', fontsize=18)

      # cross i,i+2
      ax2=plt.subplot(gs[2])
      i1 = 2
      for iBin1 in range(self.nBins-2):
         d = self.L * self.dataVector[i1*self.nL:(i1+1)*self.nL]
         std = self.L * np.sqrt(np.diag(self.covMat[i1*self.nL:(i1+1)*self.nL, i1*self.nL:(i1+1)*self.nL]))
         #
         color = Colors[iBin1]
         ax2.errorbar(self.L, d, yerr=std, ls='-', lw=2, elinewidth=1.5, marker='.', markersize=2, color=color)
         # advance counter in data vector
         i1 += self.nBins - iBin1
      #
      ax2.set_xscale('log')
      ax2.set_yscale('log', nonposy='clip')
      #
      ax2.set_ylabel(r'$\langle g_i g_{i+2}\rangle$', fontsize=18)
      ax2.set_xlabel(r'$\ell$')
      #
      fig.savefig(self.figurePath+"/p2d_gg.pdf")
      fig.clf()



      # gs
      Colors = plt.cm.winter(1.*np.arange(self.nBins)/(self.nBins-1.))
      fig=plt.figure(1)
      ax=fig.add_subplot(111)
      #
      i1 = self.nGG
      for iBin1 in range(self.nBins):
         color = Colors[iBin1]
         for iBin2 in range(self.nBins):
            d = self.L * self.dataVector[i1*self.nL:(i1+1)*self.nL]
            std = self.L * np.sqrt(np.diag(self.covMat[i1*self.nL:(i1+1)*self.nL, i1*self.nL:(i1+1)*self.nL]))
            ax.errorbar(self.L*(1.+0.01*i1/self.nGS), d, yerr=std, ls='-', lw=1, elinewidth=1.5, marker='.', markersize=2, color=color)# label=r'$\ell \langle g_{'+str(iBin1)+'} \gamma_{'+str(iBin2)+r'}\rangle$')
            # move to next row
            i1 += 1
      #
      ax.legend(loc=1)
      ax.set_xscale('log')
      ax.set_yscale('log', nonposy='clip')
      ax.set_xlabel(r'$\ell$')
      ax.set_ylabel(r'$\ell \; C_\ell^{g\gamma}$')
      ax.set_title(r'Galaxy - galaxy lensing')
      #
      fig.savefig(self.figurePath+"/p2d_gs.pdf")
      fig.clf()


      # ss: all on same plot
      Colors = plt.cm.jet(1.*np.arange(self.nBins)/(self.nBins-1.))
      fig=plt.figure(2)
      ax=fig.add_subplot(111)
      #
      i1 = self.nGG + self.nGS
      for iBin1 in range(self.nBins):
         # add entry to caption
         color = Colors[iBin1]
         ax.plot([], [], c=color, label=r'$\langle\gamma_{i} \gamma_{i+'+str(iBin1)+r'} \rangle $')
         for iBin2 in range(iBin1, self.nBins):
            d = self.L * self.dataVector[i1*self.nL:(i1+1)*self.nL]
            #
            color = Colors[iBin2-iBin1]
            #
            std = self.L * np.sqrt(np.diag(self.covMat[i1*self.nL:(i1+1)*self.nL, i1*self.nL:(i1+1)*self.nL]))
            ax.errorbar(self.L*(1.+0.01*i1/self.nSS), d, yerr=std, ls='-', lw=1, elinewidth=1.5, marker='.', markersize=2, color=color)#, label=r'$\gamma_{'+str(iBin1)+'} \gamma_{'+str(iBin2)+'}$')
            # move to next row
            i1 += 1
      #
      ax.legend(loc=1, labelspacing=0.05, handlelength=0.4, borderaxespad=0.01)
      ax.set_xscale('log')
      ax.set_yscale('log', nonposy='clip')
      ax.set_xlabel(r'$\ell$')
      ax.set_ylabel(r'$\ell \; C_\ell^{\gamma\gamma}$')
      ax.set_title(r'Shear tomography')
      #
      fig.savefig(self.figurePath+"/p2d_ss.pdf")
      fig.clf()



   def plotUncertaintyPowerSpectra(self):
      if not self.fullCross:
         print "(function only implemented for fullCross)"
         return

      # gg: panels
      Colors = plt.cm.autumn(1.*np.arange(self.nBins)/(self.nBins-1.))
      #
      fig=plt.figure(0)
      gs = gridspec.GridSpec(3, 1)#, height_ratios=[1, 1, 1])
      gs.update(hspace=0.)
      
      # auto
      ax0=plt.subplot(gs[0])
      i1 = 0
      for iBin1 in range(self.nBins):
         d = self.dataVector[i1*self.nL:(i1+1)*self.nL]
         std = np.sqrt(np.diag(self.covMat[i1*self.nL:(i1+1)*self.nL, i1*self.nL:(i1+1)*self.nL]))
         #
         color = Colors[iBin1]
         ax0.plot(self.L, std / d, '.-', lw=2, color=color)
         # advance counter in data vector
         i1 += self.nBins - iBin1
      #
      ax0.set_xscale('log')
      ax0.set_yscale('log', nonposy='clip')
      plt.setp(ax0.get_xticklabels(), visible=False)
      #
      ax0.set_title(r'Clustering: $\sigma\left( C_\ell^{gg} \right) / C_\ell^{gg}$')
      ax0.set_ylabel(r'$g_i g_i$', fontsize=18)

      # cross i,i+1
      ax1=plt.subplot(gs[1])
      i1 = 1
      for iBin1 in range(self.nBins-1):
         d = self.dataVector[i1*self.nL:(i1+1)*self.nL]
         std = np.sqrt(np.diag(self.covMat[i1*self.nL:(i1+1)*self.nL, i1*self.nL:(i1+1)*self.nL]))
         #
         color = Colors[iBin1]
         ax1.plot(self.L, std / d, '-', lw=2, color=color)
         # advance counter in data vector
         i1 += self.nBins - iBin1
      #
      ax1.set_xscale('log')
      ax1.set_yscale('log', nonposy='clip')
      plt.setp(ax1.get_xticklabels(), visible=False)
      #
      ax1.set_ylabel(r'$g_i g_{i+1}$', fontsize=18)

      # cross i,i+2
      ax2=plt.subplot(gs[2])
      i1 = 2
      for iBin1 in range(self.nBins-2):
         d = self.dataVector[i1*self.nL:(i1+1)*self.nL]
         std = np.sqrt(np.diag(self.covMat[i1*self.nL:(i1+1)*self.nL, i1*self.nL:(i1+1)*self.nL]))
         #
         color = Colors[iBin1]
         ax2.plot(self.L, std / d, '.-', lw=2, color=color)
         # advance counter in data vector
         i1 += self.nBins - iBin1
      #
      ax2.set_xscale('log')
      ax2.set_yscale('log', nonposy='clip')
      #
      ax2.set_ylabel(r'$g_i g_{i+2}$', fontsize=18)
      ax2.set_xlabel(r'$\ell$')
      #
      fig.savefig(self.figurePath+"/sp2d_gg.pdf")
      fig.clf()
      


      # gs
      Colors = plt.cm.winter(1.*np.arange(self.nBins)/(self.nBins-1.))
      fig=plt.figure(1)
      ax=fig.add_subplot(111)
      #
      i1 = self.nGG
      for iBin1 in range(self.nBins):
         color = Colors[iBin1]
         for iBin2 in range(self.nBins):
            d = self.dataVector[i1*self.nL:(i1+1)*self.nL]
            std = np.sqrt(np.diag(self.covMat[i1*self.nL:(i1+1)*self.nL, i1*self.nL:(i1+1)*self.nL]))
            ax.plot(self.L*(1.+0.01*i1/self.nGS), std / d, '.-', lw=1, color=color)
            # move to next row
            i1 += 1
      #
      ax.legend(loc=1)
      ax.set_xscale('log')
      ax.set_yscale('log', nonposy='clip')
      ax.set_xlabel(r'$\ell$')
      ax.set_ylabel(r'$\sigma\left( C_\ell^{g\gamma} \right) / C_\ell^{g\gamma}$')
      ax.set_title(r'Galaxy-galaxy lensing')
      #
      fig.savefig(self.figurePath+"/sp2d_gs.pdf")
      fig.clf()


      # ss: all on same plot
      Colors = plt.cm.jet(1.*np.arange(self.nBins)/(self.nBins-1.))
      fig=plt.figure(2)
      ax=fig.add_subplot(111)
      #
      i1 = self.nGG + self.nGS
      for iBin1 in range(self.nBins):
         # add entry to caption
         color = Colors[iBin1]
         ax.plot([], [], c=color, label=r'$\langle\gamma_{i} \gamma_{i+'+str(iBin1)+r'} \rangle $')
         for iBin2 in range(iBin1, self.nBins):
            d = self.dataVector[i1*self.nL:(i1+1)*self.nL]
            std = np.sqrt(np.diag(self.covMat[i1*self.nL:(i1+1)*self.nL, i1*self.nL:(i1+1)*self.nL]))
            color = Colors[iBin2-iBin1]
            ax.plot(self.L*(1.+0.01*i1/self.nSS), std / d, '.-', lw=1, color=color)
            # move to next row
            i1 += 1
      #
      ax.legend(loc=1, labelspacing=0.05, handlelength=0.4, borderaxespad=0.01)
      ax.set_xscale('log')
      ax.set_yscale('log', nonposy='clip')
      ax.set_xlabel(r'$\ell$')
      ax.set_ylabel(r'$\sigma\left( C_\ell^{\gamma\gamma} \right) / C_\ell^{\gamma\gamma}$')
      ax.set_title(r'Shear tomography')
      #
      fig.savefig(self.figurePath+"/sp2d_ss.pdf")
      fig.clf()






   def plotDerivativeDataVectorCosmo(self):
      """Derivative of the data vector wrt cosmo parameters.
      """
#      # one color per cosmo param
#      Colors = plt.cm.jet(1.*np.arange(self.cosmoPar.nPar)/self.cosmoPar.nPar)
#      #
#      purple, darkmagenta, darkviolet
#      orange
#      lime, mediumspringgreen
#      darkolivegreen, darkgreen
#      r
#      royalblue, cornflowerblue
#      navy, midnightblue
#      gold, yellow
#      silver, gray, darkgray
#      saddlebrown, sienna, brown

      Colors = ['purple', 'orange', 'lime', 'darkolivegreen', 'r', 'royalblue', 'navy', 'gold', 'silver', 'saddlebrown']
      
      
#      fontsize : int or float or {'xx-small', 'x-small', 'small', 'medium', 'large', 'x-large', 'xx-large'}
#      labelspacing: vertical spacing
#      handlelength=0.5
#      handletextpad=0.01
#      columnspacing=0.4

      
      
      # gg
      fig=plt.figure(0)
      ax=fig.add_subplot(111)
      #
      # for each cosmo parameter
      for iPar in range(self.cosmoPar.nPar)[::-1]:
#      for iPar in [6]:  # Mnu
#      for iPar in [9]:  # curvature
         # plot all the 2pt functions
         for i2pt in range(self.nGG):
            dlnDdlnP = self.derivativeDataVector[iPar, i2pt*self.nL:(i2pt+1)*self.nL] / self.dataVector[i2pt*self.nL:(i2pt+1)*self.nL]
            if self.cosmoPar.fiducial[iPar] <> 0.:
               dlnDdlnP *= self.cosmoPar.fiducial[iPar]
            color = Colors[iPar]
            color = darkerLighter(color, amount=-0.5*i2pt/self.nGG)
            ax.plot(self.L, dlnDdlnP, c=color, lw=3)
         ax.plot([],[], c=Colors[iPar], label=self.cosmoPar.namesLatex[iPar])
      #
      #ax.grid()
#      ax.legend(loc=4, ncol=5, labelspacing=0.05, frameon=False, handlelength=0.4, borderaxespad=0.01)
      ax.legend(loc=4, ncol=5, labelspacing=0.07, frameon=False, handlelength=0.5, handletextpad=0.01, columnspacing=0.4, borderaxespad=0.01)
      ax.legend(loc=4, ncol=5, labelspacing=0.07, frameon=False, handlelength=0.7, handletextpad=0.1, columnspacing=0.5, borderaxespad=0.01)
      ax.set_xscale('log', nonposx='clip')
      ax.set_ylim((-4., 4.))
      ax.set_xlabel(r'$\ell$')
      ax.set_ylabel(r'$d\ln C_\ell^{gg} / d\ln \text{Param.}$')
      #
      fig.savefig(self.figurePath+"/dp2d_gg_cosmo.pdf")
      fig.clf()

      # gs
      fig=plt.figure(1)
      ax=fig.add_subplot(111)
      #
      # for each cosmo parameter
      for iPar in range(self.cosmoPar.nPar)[::-1]:
#      for iPar in range(self.cosmoPar.nPar):
#      for iPar in [9]:  # curvature
         # plot all the 2pt functions
         for i2pt in range(self.nGG, self.nGG+self.nGS):
            dlnDdlnP = self.derivativeDataVector[iPar, i2pt*self.nL:(i2pt+1)*self.nL] / self.dataVector[i2pt*self.nL:(i2pt+1)*self.nL]
            if self.cosmoPar.fiducial[iPar] <> 0.:
               dlnDdlnP *= self.cosmoPar.fiducial[iPar]
            color = Colors[iPar]
            color = darkerLighter(color, amount=-0.5*(i2pt-self.nGG)/self.nGS)
            ax.plot(self.L, dlnDdlnP, c=color, lw=3)
         ax.plot([],[], c=Colors[iPar], label=self.cosmoPar.namesLatex[iPar])
      #
      #ax.grid()
#      ax.legend(loc=4, ncol=5, labelspacing=0.05, frameon=False, handlelength=0.4, borderaxespad=0.01)
#      ax.legend(loc=4, ncol=5, labelspacing=0.07, frameon=False, handlelength=0.5, handletextpad=0.01, columnspacing=0.4, borderaxespad=0.01)
      ax.legend(loc=4, ncol=5, labelspacing=0.07, frameon=False, handlelength=0.7, handletextpad=0.1, columnspacing=0.5, borderaxespad=0.01)
      ax.set_xscale('log', nonposx='clip')
      ax.set_ylim((-4., 4.))
      ax.set_xlabel(r'$\ell$')
      ax.set_ylabel(r'$d\ln C_\ell^{gs} / d\ln \text{Param.}$')
      #
      fig.savefig(self.figurePath+"/dp2d_gs_cosmo.pdf")
      fig.clf()

      # ss
      fig=plt.figure(2)
      ax=fig.add_subplot(111)
      #
      # for each cosmo parameter
      for iPar in range(self.cosmoPar.nPar)[::-1]:
#      for iPar in range(self.cosmoPar.nPar):
#      for iPar in [9]:  # curvature
         # plot all the 2pt functions
         for i2pt in range(self.nGG+self.nGS, self.nGG+self.nGS+self.nSS):
            dlnDdlnP = self.derivativeDataVector[iPar, i2pt*self.nL:(i2pt+1)*self.nL] / self.dataVector[i2pt*self.nL:(i2pt+1)*self.nL]
            if self.cosmoPar.fiducial[iPar] <> 0.:
               dlnDdlnP *= self.cosmoPar.fiducial[iPar]
            color = Colors[iPar]
            color = darkerLighter(color, amount=-0.5*(i2pt-(self.nGG+self.nGS))/self.nSS)
            ax.plot(self.L, dlnDdlnP, c=color, lw=3)
         ax.plot([],[], c=Colors[iPar], label=self.cosmoPar.namesLatex[iPar])
      #
      #ax.grid()
#      ax.legend(loc=4, ncol=5, labelspacing=0.05, frameon=False, handlelength=0.4, borderaxespad=0.01)
#      ax.legend(loc=4, ncol=5, labelspacing=0.07, frameon=False, handlelength=0.5, handletextpad=0.01, columnspacing=0.4, borderaxespad=0.01)
      ax.legend(loc=4, ncol=5, labelspacing=0.07, frameon=False, handlelength=0.7, handletextpad=0.1, columnspacing=0.5, borderaxespad=0.01)
      ax.set_xscale('log', nonposx='clip')
      ax.set_ylim((-4., 4.))
      ax.set_xlabel(r'$\ell$')
      ax.set_ylabel(r'$d\ln C_\ell^{ss} / d\ln \text{Param.}$')
      #
      fig.savefig(self.figurePath+"/dp2d_ss_cosmo.pdf")
      fig.clf()



   def plotSingleDerivative(self, ab, i2pt, iPar):
      """Derivative of the desired 2pt function wrt the desired parameter.
      """
      print "2-pt function:", ab, i2pt
      print "Parameter:", self.fullPar.names[iPar]
      
      if ab=='gg':
         i2pt += 0
      elif ab=='gs':
         i2pt += self.nGG
      elif ab=='ss':
         i2pt += self.nGG+self.nGS
      else:
         return
      
      fig=plt.figure(0)
      ax=fig.add_subplot(111)
      #
      dlnDdlnP = self.derivativeDataVector[iPar, i2pt*self.nL:(i2pt+1)*self.nL] / self.dataVector[i2pt*self.nL:(i2pt+1)*self.nL]
      if self.fullPar.fiducial[iPar] <> 0.:
         dlnDdlnP *= self.fullPar.fiducial[iPar]
#      color = Colors[iPar]
      ax.plot(self.L, dlnDdlnP, 'b', lw=3)
      ax.plot([],[], 'b', label=self.fullPar.namesLatex[iPar])
      #
      ax.grid()
      ax.legend(loc=4, ncol=5, labelspacing=0.05, frameon=False, handlelength=0.4, borderaxespad=0.01)
      ax.set_xscale('log', nonposx='clip')
#      ax.set_ylim((-4., 4.))
      ax.set_xlabel(r'$\ell$')
      ax.set_ylabel(r'$d\ln C_\ell / d\ln \text{Param.}$')
#      ax.set_title()
      #
#      fig.savefig(self.figurePath+"/dp2d_gg_cosmo.pdf")
#      fig.clf()
      plt.show()



   ##################################################################################
   ##################################################################################


   
   def photoZRequirements(self):
      '''Here the photo-z value is such that
      sigma (delta z) = photoz
      sigma (sigma z) = 1.5 * photoz
      '''
      # values of photo-z priors to try
      nPhotoz = 101
      Photoz = np.logspace(np.log10(1.e-5), np.log10(1.), nPhotoz, 10.)
      
      # Posterior uncertainties on all parameters
      sFull = np.zeros((self.fullPar.nPar, nPhotoz))
      
      # posterior uncertainties for various combinations,
      # cosmology
      sCosmoFull = np.zeros((len(self.cosmoPar.IFull), nPhotoz))
      sCosmoLCDMMnuW0Wa = np.zeros((len(self.cosmoPar.ILCDMMnuW0Wa), nPhotoz))
      sCosmoLCDMMnu = np.zeros((len(self.cosmoPar.ILCDMMnu), nPhotoz))
      sCosmoLCDMMnuCurv = np.zeros((len(self.cosmoPar.ILCDMMnuCurv), nPhotoz))
      sCosmoLCDMW0Wa = np.zeros((len(self.cosmoPar.ILCDMW0Wa), nPhotoz))
      sCosmoLCDMW0WaCurv = np.zeros((len(self.cosmoPar.ILCDMW0WaCurv), nPhotoz))
      # photo-z
      sPhotozFull = np.zeros((self.photoZPar.nPar, nPhotoz))
      sPhotozLCDMMnuW0Wa = np.zeros((self.photoZPar.nPar, nPhotoz))
      sPhotozLCDMMnu = np.zeros((self.photoZPar.nPar, nPhotoz))
      sPhotozLCDMMnuCurv = np.zeros((self.photoZPar.nPar, nPhotoz))
      sPhotozLCDMW0Wa = np.zeros((self.photoZPar.nPar, nPhotoz))
      sPhotozLCDMW0WaCurv = np.zeros((self.photoZPar.nPar, nPhotoz))
      
      for iPhotoz in range(nPhotoz):
         photoz = Photoz[iPhotoz]
         # update the photo-z priors
         newPhotoZPar = PhotoZParams(nBins=self.nBins, dzFid=0., szFid=0.05, dzStd=photoz, szStd=photoz*1.5)
         # update the full parameter object
         newPar = self.cosmoPar.copy()
         newPar.addParams(self.galaxyBiasPar)
         newPar.addParams(self.shearMultBiasPar)
         newPar.addParams(newPhotoZPar)
         # get the new posterior Fisher matrix, including the prior
         newPar.fisher += self.fisherData
         
         # Extract full uncertainties
         sFull[:,iPhotoz] = newPar.paramUncertainties(marg=True)
         
         # Extract parameter combinations:
         #
         # Full: LCDM + Mnu + curv + w0,wa
         # reject unwanted cosmo params
         I = self.cosmoPar.IFull + range(self.cosmoPar.nPar, self.fullPar.nPar)
         par = newPar.extractParams(I, marg=False)
         if iPhotoz==0 or iPhotoz==nPhotoz-1:
            par.printParams(path=self.figurePath+"/posterior_full_photozprior_"+floatExpForm(photoz)+".txt")
         # cosmology
         parCosmoFull = par.extractParams(range(len(self.cosmoPar.IFull)), marg=True)
         sCosmoFull[:, iPhotoz] = parCosmoFull.paramUncertainties(marg=True)
         # photo-z
         parPhotozFull = par.extractParams(range(-self.photoZPar.nPar, 0), marg=True)
         sPhotozFull[:, iPhotoz] = parPhotozFull.paramUncertainties(marg=True)
         #
         # LCDM + Mnu
         # reject unwanted cosmo params
         I = self.cosmoPar.ILCDMMnu + range(self.cosmoPar.nPar, self.fullPar.nPar)
         par = newPar.extractParams(I, marg=False)
         if iPhotoz==0 or iPhotoz==nPhotoz-1:
            par.printParams(path=self.figurePath+"/posterior_ldcmmnu_photozprior_"+floatExpForm(photoz)+".txt")
         # cosmology
         parCosmoLCDMMnu = par.extractParams(range(len(self.cosmoPar.ILCDMMnu)), marg=True)
         sCosmoLCDMMnu[:, iPhotoz] = parCosmoLCDMMnu.paramUncertainties(marg=True)
         # photo-z
         parPhotozLCDMMnu = par.extractParams(range(-self.photoZPar.nPar, 0), marg=True)
         sPhotozLCDMMnu[:, iPhotoz] = parPhotozLCDMMnu.paramUncertainties(marg=True)
         #
         # LCDM + Mnu + w0,wa
         # reject unwanted cosmo params
         I = self.cosmoPar.ILCDMMnuW0Wa + range(self.cosmoPar.nPar, self.fullPar.nPar)
         par = newPar.extractParams(I, marg=False)
         if iPhotoz==0 or iPhotoz==nPhotoz-1:
            par.printParams(path=self.figurePath+"/posterior_lcdmmnuw0wa_photozprior_"+floatExpForm(photoz)+".txt")
         # cosmology
         parCosmoLCDMMnuW0Wa = par.extractParams(range(len(self.cosmoPar.ILCDMMnuW0Wa)), marg=True)
         sCosmoLCDMMnuW0Wa[:, iPhotoz] = parCosmoLCDMMnuW0Wa.paramUncertainties(marg=True)
         # photo-z
         parPhotozLCDMMnuW0Wa = par.extractParams(range(-self.photoZPar.nPar, 0), marg=True)
         sPhotozLCDMMnuW0Wa[:, iPhotoz] = parPhotozLCDMMnuW0Wa.paramUncertainties(marg=True)
         #
         # LCDM + Mnu + curv
         # reject unwanted cosmo params
         I = self.cosmoPar.ILCDMMnuCurv + range(self.cosmoPar.nPar, self.fullPar.nPar)
         par = newPar.extractParams(I, marg=False)
         if iPhotoz==0 or iPhotoz==nPhotoz-1:
            par.printParams(path=self.figurePath+"/posterior_lcdmmnucurv_photozprior_"+floatExpForm(photoz)+".txt")
         # cosmology
         parCosmoLCDMMnuCurv = par.extractParams(range(len(self.cosmoPar.ILCDMMnuCurv)), marg=True)
         sCosmoLCDMMnuCurv[:, iPhotoz] = parCosmoLCDMMnuCurv.paramUncertainties(marg=True)
         # photo-z
         parPhotozLCDMMnuCurv = par.extractParams(range(-self.photoZPar.nPar, 0), marg=True)
         sPhotozLCDMMnuCurv[:, iPhotoz] = parPhotozLCDMMnuCurv.paramUncertainties(marg=True)
         #
         # LCDM + w0,wa
         # reject unwanted cosmo params
         I = self.cosmoPar.ILCDMW0Wa + range(self.cosmoPar.nPar, self.fullPar.nPar)
         par = newPar.extractParams(I, marg=False)
         if iPhotoz==0 or iPhotoz==nPhotoz-1:
            par.printParams(path=self.figurePath+"/posterior_lcdmw0wa_photozprior_"+floatExpForm(photoz)+".txt")
         # cosmology
         parCosmoLCDMW0Wa = par.extractParams(range(len(self.cosmoPar.ILCDMW0Wa)), marg=True)
         sCosmoLCDMW0Wa[:, iPhotoz] = parCosmoLCDMW0Wa.paramUncertainties(marg=True)
         # photo-z
         parPhotozLCDMW0Wa = par.extractParams(range(-self.photoZPar.nPar, 0), marg=True)
         sPhotozLCDMW0Wa[:, iPhotoz] = parPhotozLCDMW0Wa.paramUncertainties(marg=True)
         #
         # LCDM + w0,wa + curvature
         # reject unwanted cosmo params
         I = self.cosmoPar.ILCDMW0WaCurv + range(self.cosmoPar.nPar, self.fullPar.nPar)
         par = newPar.extractParams(I, marg=False)
         if iPhotoz==0 or iPhotoz==nPhotoz-1:
            par.printParams(path=self.figurePath+"/posterior_lcdmw0wacurv_photozprior_"+floatExpForm(photoz)+".txt")
         # cosmology
         parCosmoLCDMW0WaCurv = par.extractParams(range(len(self.cosmoPar.ILCDMW0WaCurv)), marg=True)
         sCosmoLCDMW0WaCurv[:, iPhotoz] = parCosmoLCDMW0WaCurv.paramUncertainties(marg=True)
         # photo-z
         parPhotozLCDMW0WaCurv = par.extractParams(range(-self.photoZPar.nPar, 0), marg=True)
         sPhotozLCDMW0WaCurv[:, iPhotoz] = parPhotozLCDMW0WaCurv.paramUncertainties(marg=True)

      
      ##################################################################################
      # Degradation of cosmo. par., depending on photo-z prior

      def plotDegradation(sCosmo, parCosmo, path):
         fig=plt.figure(0)
         ax=fig.add_subplot(111)
         #
         # fiducial prior
         ax.axvline(0.002, color='gray')
         #
         for iPar in range(parCosmo.nPar):
#         for iPar in range(len(sCosmo)):
            ax.plot(Photoz, sCosmo[iPar, :] / sCosmo[iPar, 0], label=parCosmo.namesLatex[iPar])
         #
         ax.set_xscale('log', nonposx='clip')
#         ax.legend(loc=2)
         ax.legend(loc=2, labelspacing=0.1, frameon=False, handlelength=1.)
         ax.set_ylabel(r'$\sigma_\text{Param} / \sigma_\text{Perfect photo-z}$')
         ax.set_xlabel(r'Photo-z prior')
         #
         fig.savefig(self.figurePath+path)
         fig.clf()

      # Full: LCDM + Mnu + curv + w0,wa
      plotDegradation(sCosmoFull, parCosmoFull, "/photozreq_cosmo_deg_full.pdf")
      # LCDM + Mnu
      plotDegradation(sCosmoLCDMMnu, parCosmoLCDMMnu, "/photozreq_cosmo_deg_lcdmmnu.pdf")
      # LCDM + Mnu + w0,wa
      plotDegradation(sCosmoLCDMMnuW0Wa, parCosmoLCDMMnuW0Wa, "/photozreq_cosmo_deg_lcdmmnuw0wa.pdf")
      # LCDM + Mnu + curv
      plotDegradation(sCosmoLCDMMnuCurv, parCosmoLCDMMnuCurv, "/photozreq_cosmo_deg_lcdmmnucurv.pdf")
      # LCDM + w0,wa
      plotDegradation(sCosmoLCDMW0Wa, parCosmoLCDMW0Wa, "/photozreq_cosmo_deg_lcdmw0wa.pdf")
      # LCDM + w0,wa + curvature
      plotDegradation(sCosmoLCDMW0WaCurv, parCosmoLCDMW0WaCurv, "/photozreq_cosmo_deg_lcdmw0wacurv.pdf")


      ##################################################################################
      # Relative cosmo. par. uncertainty, depending on photo-z prior

      def relatError(sigma, par):
         """Computes relative uncertainty, except if the fiducial parameter is zero.
         In that case, return 1/absolute_uncertainty.
         """
         result = np.zeros_like(sigma)
         for iPar in range(par.nPar):
            if par.fiducial[iPar]==0.:
               result[iPar] = sigma[iPar]
            else:
               result[iPar] = sigma[iPar] / par.fiducial[iPar]
         return result

      def plotRelative(sP, par, path):
         # compute relative uncertainty
         sPOverP = relatError(sP, par)
         
         fig=plt.figure(0)
         ax=fig.add_subplot(111)
         #
         # fiducial prior
         ax.axvline(0.002, color='gray')
         #
         for iPar in range(par.nPar):
            ax.plot(Photoz, sPOverP[iPar, :], label=par.namesLatex[iPar])
         #
         ax.set_xscale('log', nonposx='clip')
         ax.set_yscale('log', nonposx='clip')
#         ax.legend(loc=2)
         ax.legend(loc=2, labelspacing=0.1, frameon=True, handlelength=1.)
         ax.set_ylabel(r'$\sigma_\text{Param} / \text{Param}$')
         ax.set_xlabel(r'Photo-z prior')
         #
         fig.savefig(self.figurePath+path)
         fig.clf()
      
      # Full: LCDM + Mnu + curv + w0,wa
      plotDegradation(sCosmoFull, parCosmoFull, "/photozreq_cosmo_deg_full.pdf")
      # LCDM + Mnu
      plotDegradation(sCosmoLCDMMnu, parCosmoLCDMMnu, "/photozreq_cosmo_deg_lcdmmnu.pdf")
      # LCDM + Mnu + w0,wa
      plotDegradation(sCosmoLCDMMnuW0Wa, parCosmoLCDMMnuW0Wa, "/photozreq_cosmo_deg_lcdmmnuw0wa.pdf")
      # LCDM + Mnu + curv
      plotDegradation(sCosmoLCDMMnuCurv, parCosmoLCDMMnuCurv, "/photozreq_cosmo_deg_lcdmmnucurv.pdf")
      # LCDM + w0,wa
      plotDegradation(sCosmoLCDMW0Wa, parCosmoLCDMW0Wa, "/photozreq_cosmo_deg_lcdmw0wa.pdf")
      # LCDM + w0,wa + curvature
      plotDegradation(sCosmoLCDMW0WaCurv, parCosmoLCDMW0WaCurv, "/photozreq_cosmo_deg_lcdmw0wacurv.pdf")


      ##################################################################################
      # Comparing various param combinations

      fig=plt.figure(10)
      ax=fig.add_subplot(111)
      #
      # fiducial prior
      ax.axvline(0.002, color='gray')
      #
      for iPar in range(parCosmoLCDMMnuW0Wa.nPar):
         ax.plot(Photoz, sCosmoFull[iPar, :] / sCosmoLCDMMnuW0Wa[iPar, :], label=parCosmoFull.namesLatex[iPar])
      #
      ax.set_xscale('log', nonposx='clip')
#      ax.legend(loc=2)
      ax.legend(loc=2, labelspacing=0.1, frameon=False, handlelength=1.)
      ax.set_ylabel(r'$\sigma_\text{Param}^\text{Full} / \sigma_\text{Param}^\text{no curv.}$')
      ax.set_xlabel(r'Photo-z prior')
      #
      fig.savefig(self.figurePath+"/photozreq_cosmo_full_over_lcdmmnuw0wa.pdf")
      fig.clf()

      
      ##################################################################################

      def plotPhotoZPosterior(sPhotoz, parPhotoz, path):
         fig=plt.figure(1)
         ax=fig.add_subplot(111)
         #
         # fiducial prior
         ax.axvline(0.002, color='gray')
         ax.axhline(0.002, color='gray')
         ax.plot(Photoz, Photoz, 'gray')
         #
         # photo-z shifts
         # add legend entry
         color = 'r'
         ax.plot([], [], color=color, label=r'$\delta z$')
         darkLight = 0.
         for iPar in range(self.nBins):
            color = 'r'
            color = darkerLighter(color, amount=darkLight)
            darkLight += -0.5 * 1./self.nBins
            ax.plot(Photoz, sPhotoz[iPar, :], color=color)
         #
         # photo-z scatter
         # add legend entry
         color = 'b'
         ax.plot([], [], color=color, label=r'$\sigma_z / (1+z)$')
         darkLight = 0.
         for iPar in range(self.nBins, 2*self.nBins):
            color = 'b'
            color = darkerLighter(color, amount=darkLight)
            darkLight += -0.5 * 1./self.nBins
            ax.plot(Photoz, sPhotoz[iPar, :], color=color)
         #
         ax.set_xscale('log', nonposx='clip')
         ax.set_yscale('log', nonposx='clip')
         ax.legend(loc=2)
         ax.set_ylabel(r'$\sigma_\text{Param}$')
         ax.set_xlabel(r'Photo-z prior')
         #
         fig.savefig(self.figurePath+path)
         fig.clf()

      # Full: LCDM + Mnu + curv + w0,wa
      plotPhotoZPosterior(sPhotozFull, parPhotozFull, "/photozreq_photoz_full.pdf")
      # LCDM + Mnu
      plotPhotoZPosterior(sPhotozLCDMMnu, parPhotozLCDMMnu, "/photozreq_photoz_lcdmmnu.pdf")
      # LCDM + Mnu + w0,wa
      plotPhotoZPosterior(sPhotozLCDMMnuW0Wa, parPhotozLCDMMnuW0Wa, "/photozreq_photoz_lcdmmnuw0wa.pdf")
      # LCDM + Mnu + curv
      plotPhotoZPosterior(sPhotozLCDMMnuCurv, parPhotozLCDMMnuCurv, "/photozreq_photoz_lcdmmnucurv.pdf")
      # LCDM + w0,wa
      plotPhotoZPosterior(sPhotozLCDMW0Wa, parPhotozLCDMW0Wa, "/photozreq_photoz_lcdmw0wa.pdf")
      # LCDM + w0,wa + curvature
      plotPhotoZPosterior(sPhotozLCDMW0WaCurv, parPhotozLCDMW0WaCurv, "/photozreq_photoz_lcdmw0wacurv.pdf")


#      # photo-z parameters
#      fig=plt.figure(10)
#      ax=fig.add_subplot(111)
#      #
#      # fiducial prior
#      ax.axvline(0.002, color='gray')
#      #
#      # photo-z shifts
#      IPar = self.cosmoPar.nPar+self.galaxyBiasPar.nPar+self.shearMultBiasPar.nPar
#      IPar += np.arange(self.nBins)
#      # add legend entry
#      color = 'r'
#      ax.plot([], [], color=color, label=r'$\delta z$')
#      for iPar in IPar:
#         color = 'r'
#         ax.plot(Photoz, sigmasFull[iPar, :], color=color)#, label=self.fullPar.namesLatex[iPar])
#      #
#      # photo-z scatter
#      IPar = self.cosmoPar.nPar+self.galaxyBiasPar.nPar+self.shearMultBiasPar.nPar + self.nBins
#      IPar += np.arange(self.nBins)
#      # add legend entry
#      color = 'b'
#      ax.plot([], [], color=color, label=r'$\sigma_z / (1+z)$')
#      for iPar in IPar:
#         color = 'b'
#         ax.plot(Photoz, sigmasFull[iPar, :], color=color)#, label=self.fullPar.namesLatex[iPar])
#      #
#      ax.set_xscale('log', nonposx='clip')
#      ax.set_yscale('log', nonposx='clip')
#      ax.legend(loc=2)
#      ax.set_ylabel(r'$\sigma_\text{Param}$')
#      ax.set_xlabel(r'Photo-z prior')
#      #
#      fig.savefig(self.figurePath+"/photozreq_photoz_full.pdf")





   ##################################################################################
   ##################################################################################


   def shearBiasRequirements(self):
      # values of shear priors to try
      nM = 101
      M = np.logspace(np.log10(1.e-5), np.log10(1.), nM, 10.)
      
      # parameters to plot
      sigmasFull = np.zeros((self.fullPar.nPar, nM))
      
      for iM in range(nM):
         m = M[iM]
         # update the shear bias priors
         shearMultBiasPar = ShearMultBiasParams(nBins=self.nBins, mStd=m)
         
         # update the full parameter object
         newPar = self.cosmoPar.copy()
         newPar.addParams(self.galaxyBiasPar)
         newPar.addParams(shearMultBiasPar)
         newPar.addParams(self.photoZPar)
         # get the new posterior Fisher matrix
         newPar.fisher += self.fisherData
         
         # LCDM + Mnu + curvature + w0, wa
         # compute uncertainties with prior
         invFisher = np.linalg.inv(newPar.fisher)
         # get marginalized uncertainties
         std = np.sqrt(np.diag(invFisher))
         sigmasFull[:, iM] = std



      # cosmological parameters
      IPar = range(self.cosmoPar.nPar)
      fig=plt.figure(0)
      ax=fig.add_subplot(111)
      #
      # fiducial value
      ax.axvline(0.005, color='gray', alpha=0.5)
      #
      for iPar in IPar:
         ax.plot(M, sigmasFull[iPar, :] / sigmasFull[iPar, 0], label=self.fullPar.namesLatex[iPar])
      #
      ax.set_xscale('log', nonposx='clip')
      ax.legend(loc=2)
      ax.set_ylabel(r'$\sigma_\text{Param} / \sigma_\text{Perfect shear bias}$')
      ax.set_xlabel(r'Shear bias prior')

      # shear bias parameters
      fig=plt.figure(1)
      ax=fig.add_subplot(111)
      #
      # fiducial prior
      ax.axvline(0.005, color='gray')
      #
      IPar = self.cosmoPar.nPar+self.galaxyBiasPar.nPar
      IPar += np.arange(self.nBins)
      for iPar in IPar:
         color = plt.cm.autumn((iPar-IPar[0])/(len(IPar)-1.))
         ax.plot(M, sigmasFull[iPar, :], color=color, label=self.fullPar.namesLatex[iPar])
      #
      ax.set_xscale('log', nonposx='clip')
      ax.set_yscale('log', nonposy='clip')
      ax.legend(loc=2, labelspacing=0.05, handlelength=0.4, borderaxespad=0.01)
      ax.set_ylabel(r'$\sigma_\text{Param}$')
      ax.set_xlabel(r'Shear bias prior')

      plt.show()







































