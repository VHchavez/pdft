import numpy as np 
from opt_einsum import contract
import matplotlib.pyplot as plt
import psi4

class Inversion():
    def __init__(self, fragments, molecule):
        
        #Basics
        self.frags    = fragments
        self.nfrag    = len(fragments)
        self.molecule = molecule
        self.nbf      = self.molecule.nbf
        self.nblocks  = self.assert_grid_elements()

        #From methods
        self.frag_e     = None 
        self.frag_da_nm = None
        self.frag_db_nm = None
        self.frag_da_r  = None
        self.frag_db_r  = None
        self.frag_orbitals_r = None
        self.get_frag_energies()
        self.get_frag_densities_nm()
        self.get_frag_densities_r()
        
        #From inversion
        self.vp     = None
        self.ep     = None

    def assert_grid_elements(self):
        """
        Asserts if density on the grid is avaliable. 
        If so, asserts that grid points are same between molecules and fragments. 
        """

        if len(self.molecule.ingredients["density"]["da"]) == 0:
            raise ValueError("Density on the grid not avaliable for molecule. Please run scf with get_ingredients as True")

        if len(self.frags[0].ingredients["density"]["da"]) == 0:
            raise ValueError("Density on the grid not avaliable for molecule. Please run scf with get_ingredients as True")

        #Checks that the number of points in each block for framgent is same wrt molecule
        mol_points = psi4.driver.p4util.python_helpers._core_vbase_get_np_xyzw(self.molecule.Vpot)
        fra_points = psi4.driver.p4util.python_helpers._core_vbase_get_np_xyzw(self.frags[0].Vpot)

        if len(mol_points[0]) != len(fra_points[0]):
            raise ValueError("Grid of fragments does not match Grid of molecule. Try incresing DFT_SPHERICAL_POINTS")

        else:
            return self.molecule.Vpot.nblocks()

        

    def get_frag_energies(self):
        """
        Adds fragment energies for fragments
        """
        frag_energy = 0.0
        for frag in self.frags:
            frag_energy += frag.energy
        self.frag_energy = frag_energy

    def get_frag_densities_nm(self):
        """
        Adds fragment densities in their AO orbital representation 
        """
        sum_a = psi4.core.Matrix.from_array(np.zeros((self.nbf, self.nbf)))
        sum_b = psi4.core.Matrix.from_array(np.zeros((self.nbf, self.nbf)))
        for frag in self.frags:
            sum_a.axpy(1.0, frag.Da)
            sum_b.axpy(1.0, frag.Db)
        self.frag_da_nm = sum_a
        self.frag_db_nm = sum_b

    def get_frag_densities_r(self):
        """
        Adds fragment densities on the grid in blocks
        """
        sum_a = []
        sum_b = []

        for block in range(self.nblocks):
            block_sum_a = np.zeros_like(self.molecule.ingredients["density"]["da"][block])
            block_sum_b = np.zeros_like(self.molecule.ingredients["density"]["db"][block])
            for frag in self.frags:
                block_sum_a += frag.ingredients["density"]["da"][block]
                block_sum_b += frag.ingredients["density"]["db"][block]
            sum_a.append(block_sum_a)
            sum_b.append(block_sum_b)
        self.frag_da_r = sum_a
        self.frag_db_r = sum_b

    def get_delta_density(self, option):
        """
        Calculates density difference on the grid/AObasis for current frag densities
        """ 
        if option == "grid":
            dd_a = []
            dd_b = []
            l1error = 0.0
            for block in range(self.nblocks): 
                block_dd_a =  self.frag_da_r[block] - self.molecule.ingredients["density"]["da"][block]
                block_dd_b =  self.frag_db_r[block] - self.molecule.ingredients["density"]["db"][block]
                dd_a.append(block_dd_a)
                dd_b.append(block_dd_b)
                l1error += np.abs(contract('p,p->', block_dd_a, self.molecule.ingredients["grid"]["w"][block]))     
                l1error += np.abs(contract('p,p->', block_dd_b, self.molecule.ingredients["grid"]["w"][block]))   
            return dd_a, dd_b, l1error

        if option == "matrix":
            dd_a = self.molecule.Da.np - self.frag_da_nm.np
            dd_b = self.molecule.Db.np - self.frag_db_nm.np
            return dd_a, dd_b

    def get_ep(self):
        """
        Finds partition energy for current fragment densities
        """
        ep = self.molecule.energy - self.molecule.Enuc
        for frag in self.frags:
            ep -= (frag.energy - frag.Enuc)
        self.ep = ep

    def axis_plot(self, axis, matrices, grid, threshold=1e-8):
        """

        For a given matrix in AO basis set, plots the value for that matrix along a given axis. 

        """    
        y_arrays = []

        for i, matrix in enumerate(matrices):

            #matrix = matrix.np
            #density_grid, grid = self.basis_to_grid(matrix, blocks=False)
            density_grid = matrix

            x = []
            y = []
    
            if axis == "z":
                for i in range(len(grid[0])):
                    if np.abs(grid[0][i]) < threshold:
                        if np.abs(grid[1][i]) < threshold:
                            x.append((grid[2][i]))
                            y.append(density_grid[i])

            elif axis == "y":
                for i in range(len(grid[0])):
                    if np.abs(grid[0][i]) < threshold:
                        if np.abs(grid[2][i]) < threshold:
                            x.append((grid[1][i]))
                            y.append(density_grid[i])

            elif axis == "x":
                for i in range(len(grid[0])):
                    if np.abs(grid[1][i]) < threshold:
                        if np.abs(grid[2][i]) < threshold:
                            x.append((grid[0][i]))
                            y.append(density_grid[i])


            x = np.array(x)
            y = np.array(y)
            indx = x.argsort()
            x = x[indx]
            y = y[indx]
            y_arrays.append(y)

        return x, y_arrays

    # Inversion Procedures

    def vp_handler(self, method, beta, maxiter=40, atol=1e-5,
                  guess=None, print_scf=True, plot_scf=True):

        vp_a = psi4.core.Matrix(self.nbf, self.nbf)
        vp_b = psi4.core.Matrix(self.nbf, self.nbf)

        if guess == "hartree":
            return 
        elif guess == "xc":
            # vp_a += self.molecule.ingredients["vxc"] - (self.frags[0].ingredients["vxc"] + self.frags[1].ingredients["vxc"])
            # vp_a /=2
            # vp_b += self.molecule.ingredients["vxc"] - (self.frags[0].ingredients["vxc"] + self.frags[1].ingredients["vxc"])
            # vp_b /=2
            #vp_a +=  self.molecule.wfn.V() - ()
            return
        elif guess == "hxc":
            return 

        l1_list = []
        ep_list = []
        for step in range(maxiter+1):
            #Update fragment densities
            for frag in self.frags:
                frag.scf(vp_mn=[vp_a, vp_b], get_ingredients=True, get_orbitals=True)

            #Check convergence
            self.get_frag_energies()
            self.get_frag_densities_r()
            self.get_frag_densities_nm()
            self.get_ep()
            dd_a, dd_b, error = self.get_delta_density(option="grid")
            dd_a_mn, dd_b_mn  = self.get_delta_density(option="matrix")
            l1_list.append(error)
            ep_list.append(self.ep)
            if print_scf is True:
                print(F"vp scf cycle: {step} | Density Difference: {error:.5f} | Ep: {self.ep:.5f} | Ef: {self.frag_energy:.4f}")

            #Choose inversion method
            if method == "zpm":
                dvp_a, dvp_b = self.vp_zpm(dd_a_mn, dd_b_mn)
            elif method == "dd":
                dvp_a, dvp_b = self.vp_dd(dd_a_mn, dd_b_mn)
            elif method == "zc":
                dvp_a, dvp_b = self.vp_zc(dd_a_mn, dd_b_mn)
            elif method == "wy_r":
                dvp_a, dvp_b = self.vp_wy_r(dd_a, dd_b)
 
            #Update vp
            dvp_a = psi4.core.Matrix.from_array(dvp_a)
            dvp_b = psi4.core.Matrix.from_array(dvp_b)
            vp_a.axpy(beta, dvp_a)
            vp_b.axpy(beta, dvp_b)
            self.vp = [vp_a, vp_b]

            #Plot
            if plot_scf is True:
                vp, grid = self.molecule.basis_to_grid(vp_a.np + vp_b.np, blocks=False)
                dvp, _ = self.molecule.basis_to_grid(dvp_a.np + dvp_b.np, blocks=False)
                nmol,  _ = self.molecule.basis_to_grid(self.molecule.Da.np + self.molecule.Db.np, blocks=False)
                nfrag, _ = self.molecule.basis_to_grid(self.frag_da_nm.np + self.frag_db_nm.np, blocks=False)
                x, ys = self.axis_plot("z", [vp, dvp, nmol, nfrag], grid)

                fig, ax = plt.subplots(nrows=2, ncols=2, figsize=(9,5))

                p1 = ax[0][0]
                p2 = ax[1][0]
                p3 = ax[0][1]
                p4 = ax[1][1]

                p1.plot(l1_list, label="L1 Error")
                p1.set_xlabel("SCF Cycle")
                p1.set_ylabel("L1 Density Difference Error")
                p1.legend()

                p2.plot(x, ys[2], label="mol_density")
                p2.plot(x, ys[3], label="frag_density")
                p2.set_xlabel("z")
                p2.set_ylabel("Fragment Density")
                p2.legend()
                p2.set_ylim(-0.01, 0.2)
                p2.set_xlim(-10,10)

                p3.plot(x,ys[0], label="vp")
                #   p3.plot(x,ys[1], label="dvp")
                #p3.plot(x_dvp, y_dvp, label="dvp")
                # p3.plot(vnad_xc_x, vnad_xc_y, label="vnad_xc", linestyle=":")
                # p3.plot(vnad_ha_x, vnad_ha_y, label="vnad_ha", linestyle=":")
                p3.set_xlabel("X")
                p3.set_ylabel("vp")
                p3.set_xlim(-7,7)
                #p3.set_ylim(-1.0,1.0)
                p3.legend()


                p4.plot(x, np.log10(np.abs(ys[2] - ys[3])), label="log10(DD)")
                p4.set_xlabel("X")
                p4.set_ylabel("n_mol - sum(n_i)")
                #p4.set_xlim(-10,10)
                p4.legend()

                fig.tight_layout()
                plt.show()

            if step == maxiter:
                raise Exception("Maximum number of SCF cycles exceeded for vp")

    def vp_wy_r(self, dd_a, dd_b):
        """ 
        Performs the Wu-Yang Method on the grid
        """

        dvp = np.zeros_like(self.molecule.Da)
        dd = dd_a + dd_b 

        #Bring grid information
        points_func = self.molecule.Vpot.properties()[0]
        #points_func = self.frags[0].Vpot.properties()[0]

        if self.nblocks != self.molecule.Vpot.nblocks():
            raise Exception("Number of blocks is inconsistent")
        
        #Calculate denominator

        for block in range(self.molecule.Vpot.nblocks()):
            grid_block = self.molecule.Vpot.get_block(block)
            #grid_block = self.frags[0].Vpot.get_block(block)
            points_func.compute_points(grid_block)
            npoints = grid_block.npoints()
            lpos = np.array(grid_block.functions_local_to_global())
            w = np.array(grid_block.w())
            phi = np.array(points_func.basis_values()["PHI"])[:npoints, :lpos.shape[0]]

            x_a = np.zeros((npoints, npoints))
            x_b = np.zeros((npoints, npoints))

            for frag in self.frags:
                orb_a = frag.orbitals["alpha_r"]
                orb_b = frag.orbitals["beta_r"]
                
                for i_occ in range(0,frag.nalpha):
                    for i_vir in range(frag.nalpha, frag.nbf):
                        
                        den = frag.eigs_a.np[i_occ] - frag.eigs_a.np[i_vir]
                        num = np.zeros((npoints, npoints))

                        for r1 in range(npoints):
                            for r2 in range(npoints):
                                num[r1, r2] = orb_a[str(i_occ)][block][r1] * orb_a[str(i_vir)][block][r1] * orb_a[str(i_vir)][block][r2] * orb_a[str(i_occ)][block][r2]        
                        x_a += num / den

                # num = np.zeros((self.nbf, self.nbf))
                # for i_occ in range(0,frag.nbeta):
                #     for i_vir in range(frag.nbeta, frag.nbf):
                #         num = orb_b[str(i_occ)][block] * orb_b[str(i_vir)][block] * orb_b[str(i_vir)][block] * orb_b[str(i_occ)][block]
                #         den = frag.eigs_b.np[i_occ] - frag.eigs_b.np[i_vir]
                #         x_b += num/den

            dvp_block = np.zeros((npoints))
            for r1 in range(npoints):
                dvp_block += (1 / (x_a[r1, :] + x_a[r1, :])) * dd[block] * w  

            #xinv = 1 / (x_a + x_a)
            #dvp_block = xinv * dd[block]

            vtmp = contract('pb,p,p,pa->ab', phi, dvp_block, w, phi)
            dvp[(lpos[:, None], lpos)] += 0.5 * (vtmp + vtmp.T)

        return dvp, dvp

    def vp_zpm(self, dd_a, dd_b):
        """
        Performs the Zhao-Morrison-Parr Inversion
        Physical Review A, 50(3):2138, 1994.
        """
        dvp_a = (-0.5) * contract('imlj, ml->ij', self.molecule.mints.ao_eri().np, dd_a)
        dvp_b = (-0.5) * contract('imlj, ml->ij', self.molecule.mints.ao_eri().np, dd_b)
        return dvp_a, dvp_b

    def vp_dd(self, dd_a, dd_b):
        """
        Performs density difference inversion. 
        That is dvp = beta * (dd_a + dd_b)
        """
        dvp_a = dd_a 
        dvp_b = dd_b
        return dvp_a, dvp_b 

    def vp_zc(self, da_mn, db_mn, rcond=1e-6):
        """
        Performs the Zhang-Carter Inversion
        J. Chem. Phys. 148, 034105 (2018)
        """        

        nbf = self.molecule.nbf
        dd = da_mn + db_mn

        nalpha =  self.molecule.nalpha
        nbeta = self.molecule.nbeta
        
        for frag in self.frags:

            if self.molecule.nalpha == self.molecule.nbeta:
                
                x = np.zeros((nbf, nbf, nbf, nbf))

                Ca = frag.Ca.np 
                Cb = frag.Cb.np

                #eigs_a = frag.eigs_a.np[:nalpha,None] - frag.eigs_a.np[nalpha:]
                #eigs_b = frag.eigs_b.np[:nbeta, None] - frag.eigs_b.np[nbeta:]

                for i in range(0, self.molecule.nalpha):
                    for a in range(self.molecule.nalpha, nbf):
                        x += contract('mi, na, li, sa -> mnls', Ca[None,i], Ca[None,a], Ca[None,i], Ca[None,a], optimize=True) / (frag.eigs_a.np[i] - frag.eigs_a.np[a])
                        x += contract('mi, na, li, sa -> mnls', Cb[None,i], Cb[None,a], Cb[None,i], Cb[None,a], optimize=True) / (frag.eigs_b.np[i] - frag.eigs_b.np[a])
                        #x += np.einsum('m, n, l, s -> mnls', Ca[:,i], Ca[:,a], Ca[:,i], Ca[:,a], optimize=True) / (frag.eigs_a.np[i] - frag.eigs_a.np[a])
                        #x += np.einsum('m, n, l, s -> mnls', Cb[:,i], Cb[:,a], Cb[:,i], Cb[:,a], optimize=True) / (frag.eigs_b.np[i] - frag.eigs_b.np[a])


                #x_y += np.einsum('mi, na, li, sa, ia -> mnls', Ca[:,:nalpha], Ca[:,nalpha:], Ca[:,:nalpha], Ca[:,nalpha:], np.reciprocal(eigs_a),optimize=True)
                #x_y += np.einsum('mi, na, li, sa, ia -> mnls', Cb[:,:nbeta], Cb[:,nbeta:], Cb[:,:nbeta], Cb[:,nbeta:], np.reciprocal(eigs_b),optimize=True)

            # else:

            #     xa = np.zeros((nbf, nbf, nbf, nbf))
            #     xb = np.zeros((nbf, nbf, nbf, nbf))

            #     for i in range(0, self.molecule.nalpha):
            #         for a in range(self.molecule.nalpha, nbf):
            #             xa += np.einsum('m, n, l, s -> mnls', frag.C_a.np[None,i], frag.C_a.np[None,a], frag.C_a.np[None,i], frag.C_a.np[None,a], optimize=True) / (frag.eigs_a.np[i] - frag.eigs_a.np[a])

            #     for i in range(0, self.molecule.nbeta):
            #         for a in range(self.molecule.nbeta, nbf):
            #             xb += np.einsum('m, n, l, s -> mnls', frag.C_b.np[None,i], frag.C_b.np[None,a], frag.C_b.np[None,i], frag.C_b.np[None,a], optimize=True) / (frag.eigs_b.np[i] - frag.eigs_b.np[a])



        #x = 0.5 * (x + x.T)
        x_inv = np.linalg.pinv(x)
        #print("min value of x_inv", np.min(np.abs(x_inv)))
        dvp = contract('mnls, ls -> mn', x_inv, dd)
        dvp = 0.5 * (dvp + dvp.T)

        return dvp, dvp